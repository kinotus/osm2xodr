import argparse
import math
from pathlib import Path

from PIL import Image

from OSMParser.osmParsing import parseAll
from OSMParser.xodrWriting import (
    fillJunctionRoads,
    fillNormalRoads,
    startBasicXODRFile,
)


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert OSM XML files to OpenDRIVE."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="OSM file(s) to convert. Defaults to map.osm.",
    )
    parser.add_argument(
        "--batch",
        nargs="?",
        const=Path("data") / "osm",
        type=Path,
        metavar="DIR",
        help="convert every .osm file in DIR (default: data/osm)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output file for a single input (default: output.xodr)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="directory for batch or multiple-input output files",
    )
    topography_group = parser.add_mutually_exclusive_group()
    topography_group.add_argument(
        "--topography",
        type=Path,
        help="optional topography image; defaults to topomap.png without --batch",
    )
    topography_group.add_argument(
        "--no-topography",
        action="store_true",
        help="disable the default topography image",
    )
    parser.add_argument(
        "--minimum-height",
        type=float,
        help=(
            "minimum elevation represented by the topography image; "
            "defaults to image metadata or 163.0"
        ),
    )
    parser.add_argument(
        "--maximum-height",
        type=float,
        help=(
            "maximum elevation represented by the topography image; "
            "defaults to image metadata or 192.0"
        ),
    )
    parser.add_argument(
        "--curve-radius",
        type=float,
        default=12.0,
        help="curve radius passed to the converter",
    )
    return parser


def collect_inputs(args, parser):
    if args.batch is not None:
        if args.inputs:
            parser.error("positional inputs cannot be combined with --batch")
        if args.output is not None:
            parser.error("--output cannot be combined with --batch; use --output-dir")
        inputs = sorted(path for path in args.batch.glob("*.osm") if path.is_file())
        if not inputs:
            parser.error(f"no .osm files found in batch directory: {args.batch}")
        return inputs

    inputs = args.inputs or [Path("map.osm")]
    if args.output is not None and len(inputs) != 1:
        parser.error("--output can only be used with one input file")
    return inputs


def output_path(source, args, input_count):
    if args.output is not None:
        return args.output
    if input_count == 1 and not args.batch:
        return Path("output.xodr")
    return args.output_dir / f"{source.stem}.xodr"


def resolve_topography(source, args):
    if args.no_topography:
        return None
    if args.topography is not None:
        topography = args.topography
    else:
        adjacent = source.with_suffix(".png")
        topography = adjacent if adjacent.is_file() else None
        if topography is None and args.batch is None and not args.inputs:
            fallback = Path("topomap.png")
            topography = fallback if fallback.is_file() else None

    if topography is not None and not topography.is_file():
        raise FileNotFoundError(f"topography image not found: {topography}")
    return topography


def resolve_height_range(topography, args):
    minimum = args.minimum_height
    maximum = args.maximum_height

    if topography is not None and (minimum is None or maximum is None):
        with Image.open(topography) as image:
            metadata = image.info
        if minimum is None:
            minimum = _finite_metadata_value(
                metadata, "elevation_minimum", topography
            )
        if maximum is None:
            maximum = _finite_metadata_value(
                metadata, "elevation_maximum", topography
            )

    minimum = 163.0 if minimum is None else minimum
    maximum = 192.0 if maximum is None else maximum
    if minimum >= maximum:
        raise ValueError(
            f"minimum height ({minimum}) must be below maximum height ({maximum})"
        )
    return minimum, maximum


def _finite_metadata_value(metadata, key, topography):
    if key not in metadata:
        return None
    try:
        value = float(metadata[key])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{topography}: invalid {key} metadata") from error
    if not math.isfinite(value):
        raise ValueError(f"{topography}: non-finite {key} metadata")
    return value


def convert_file(source, destination, args):
    if not source.is_file():
        raise FileNotFoundError(f"OSM input file not found: {source}")

    topography = resolve_topography(source, args)
    minimum_height, maximum_height = resolve_height_range(topography, args)

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Converting {source} -> {destination}")
    if topography is not None:
        print(
            f"  Topography: {topography} "
            f"({minimum_height:.3f} to {maximum_height:.3f} m)"
        )
    parseAll(
        str(source),
        bildpfad=str(topography) if topography is not None else None,
        minimumHeight=minimum_height,
        maximumHeight=maximum_height,
        curveRadius=args.curve_radius,
    )
    startBasicXODRFile(str(destination))
    fillNormalRoads(str(destination))
    fillJunctionRoads(str(destination))


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    inputs = collect_inputs(args, parser)

    for source in inputs:
        convert_file(source, output_path(source, args, len(inputs)), args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
