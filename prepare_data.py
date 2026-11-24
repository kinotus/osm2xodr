#!/usr/bin/env python3
import argparse
import math
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import numpy as np
from PIL import Image, PngImagePlugin
from pyproj import Transformer


DEFAULT_WCS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wcs"
DEFAULT_COVERAGE = "avoindata:Korkeusmalli_2021_1m"
DEFAULT_NODATA = -32767.0
MAX_UINT16 = 65535


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _validated_bbox(min_lon, min_lat, max_lon, max_lat):
    values = tuple(float(value) for value in (min_lon, min_lat, max_lon, max_lat))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("OSM bounding box contains a non-finite coordinate")

    min_lon, min_lat, max_lon, max_lat = values
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("OSM bounding box is empty or has invalid coordinates")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise ValueError("OSM longitude is outside the WGS84 longitude range")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValueError("OSM latitude is outside the WGS84 latitude range")
    return values


def read_osm_bbox(path):
    node_bbox = [math.inf, math.inf, -math.inf, -math.inf]
    has_nodes = False

    for _, element in ElementTree.iterparse(str(path), events=("end",)):
        element_name = _local_name(element.tag)
        if element_name == "bounds":
            try:
                bbox = _validated_bbox(
                    element.get("minlon"),
                    element.get("minlat"),
                    element.get("maxlon"),
                    element.get("maxlat"),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}: invalid <bounds> element: {error}") from error
            element.clear()
            return bbox

        if element_name == "node":
            try:
                lon = float(element.get("lon"))
                lat = float(element.get("lat"))
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}: node has invalid coordinates: {error}") from error
            node_bbox = [
                min(node_bbox[0], lon),
                min(node_bbox[1], lat),
                max(node_bbox[2], lon),
                max(node_bbox[3], lat),
            ]
            has_nodes = True

        if element_name in ("node", "way", "relation"):
            element.clear()

    if not has_nodes:
        raise ValueError(f"{path}: no <bounds> element or georeferenced nodes found")

    return _validated_bbox(*node_bbox)


def project_bbox(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3879", always_xy=True)
    longitudes = [min_lon, min_lon, max_lon, max_lon]
    latitudes = [min_lat, max_lat, min_lat, max_lat]
    eastings, northings = transformer.transform(longitudes, latitudes)
    return min(eastings), min(northings), max(eastings), max(northings)


def build_coverage_url(endpoint, coverage, bbox, resolution):
    min_easting, min_northing, max_easting, max_northing = bbox
    width = max(1, math.ceil((max_easting - min_easting) / resolution))
    height = max(1, math.ceil((max_northing - min_northing) / resolution))
    parameters = {
        "service": "WCS",
        "version": "1.0.0",
        "request": "GetCoverage",
        "coverage": coverage,
        "crs": "EPSG:3879",
        "response_crs": "EPSG:3879",
        "bbox": ",".join(
            (
                f"{min_easting:.6f}",
                f"{min_northing:.6f}",
                f"{max_easting:.6f}",
                f"{max_northing:.6f}",
            )
        ),
        "width": str(width),
        "height": str(height),
        "format": "GeoTIFF",
    }
    return f"{endpoint}?{urlencode(parameters)}", width, height


def download_geotiff(url, destination, timeout):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    request = Request(url, headers={"User-Agent": "osm2xodr/prepare-data"})

    try:
        with urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
            first_chunk = response.read(64 * 1024)
            if not first_chunk.startswith((b"II*\x00", b"MM\x00*")):
                content_type = response.headers.get("Content-Type", "unknown")
                raise ValueError(
                    f"WCS server returned {content_type}, not a GeoTIFF"
                )
            output.write(first_chunk)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_nodata(image):
    value = image.tag_v2.get(42113)  # GDAL_NODATA
    if value is None:
        return DEFAULT_NODATA
    if isinstance(value, (tuple, list)):
        value = value[0]
    if isinstance(value, bytes):
        value = value.decode("ascii")
    return float(str(value).split()[0])


def convert_geotiff_to_png(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")

    try:
        with Image.open(source) as image:
            elevations = np.asarray(image, dtype=np.float64)
            if elevations.ndim != 2:
                raise ValueError(f"{source}: expected a single-band elevation raster")
            nodata = _read_nodata(image)

        valid = np.isfinite(elevations) & (elevations != nodata)
        if not np.any(valid):
            raise ValueError(f"{source}: elevation raster has no valid pixels")

        minimum = float(np.min(elevations[valid]))
        maximum = float(np.max(elevations[valid]))
        encoded = np.zeros(elevations.shape, dtype=np.uint16)
        if maximum > minimum:
            encoded[valid] = np.rint(
                (elevations[valid] - minimum) * MAX_UINT16 / (maximum - minimum)
            ).astype(np.uint16)

        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("elevation_minimum", repr(minimum))
        metadata.add_text("elevation_maximum", repr(maximum))
        metadata.add_text("vertical_reference", "N2000")
        Image.fromarray(encoded).save(temporary, format="PNG", pnginfo=metadata)
        temporary.replace(destination)
        return minimum, maximum
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_file(source, output_dir, endpoint, coverage, resolution, timeout):
    wgs84_bbox = read_osm_bbox(source)
    projected_bbox = project_bbox(wgs84_bbox)
    url, width, height = build_coverage_url(
        endpoint, coverage, projected_bbox, resolution
    )
    output_directory = output_dir or source.parent
    geotiff_destination = output_directory / f"{source.stem}.tif"
    png_destination = output_directory / f"{source.stem}.png"
    print(
        f"{source}: WGS84 bbox "
        f"({wgs84_bbox[0]:.7f}, {wgs84_bbox[1]:.7f}, "
        f"{wgs84_bbox[2]:.7f}, {wgs84_bbox[3]:.7f})"
    )
    print(f"  Downloading {width} x {height} GeoTIFF -> {geotiff_destination}")
    download_geotiff(url, geotiff_destination, timeout)
    minimum, maximum = convert_geotiff_to_png(
        geotiff_destination, png_destination
    )
    print(
        f"  Converted 16-bit PNG -> {png_destination} "
        f"(N2000 range {minimum:.3f} to {maximum:.3f} m)"
    )


def create_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare Helsinki elevation GeoTIFFs and 16-bit PNGs for OSM files "
            "by downloading the matching WCS coverage."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data") / "osm",
        help="directory containing .osm files (default: data/osm)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="output directory (default: next to each .osm file)",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="output pixel size in metres (default: 1)",
    )
    parser.add_argument(
        "--wcs-url",
        default=DEFAULT_WCS_URL,
        help="Helsinki WCS endpoint",
    )
    parser.add_argument(
        "--coverage",
        default=DEFAULT_COVERAGE,
        help="WCS 1.0.0 coverage name",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout per download in seconds (default: 120)",
    )
    return parser


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.resolution <= 0:
        parser.error("--resolution must be greater than zero")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if not args.input_dir.is_dir():
        parser.error(f"input directory not found: {args.input_dir}")

    sources = sorted(args.input_dir.glob("*.osm"))
    if not sources:
        parser.error(f"no .osm files found in: {args.input_dir}")

    failures = 0
    for source in sources:
        try:
            prepare_file(
                source,
                args.output_dir,
                args.wcs_url,
                args.coverage,
                args.resolution,
                args.timeout,
            )
        except (ElementTree.ParseError, OSError, URLError, ValueError) as error:
            failures += 1
            print(f"{source}: failed: {error}", file=sys.stderr)

    if failures:
        print(f"{failures} of {len(sources)} files failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
