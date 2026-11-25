import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

from prepare_data import (
    analyze_geotiff,
    build_coverage_url,
    build_map_url,
    convert_geotiff_to_png,
    project_bbox,
    read_osm_bbox,
    write_elevation_sidecar,
)


class ReadOsmBboxTests(unittest.TestCase):
    def test_prefers_osm_bounds_over_referenced_nodes(self):
        contents = """\
<?xml version="1.0"?>
<osm version="0.6">
  <bounds minlat="60.0" minlon="24.0" maxlat="60.1" maxlon="24.1"/>
  <node id="1" lat="59.0" lon="23.0"/>
  <node id="2" lat="61.0" lon="25.0"/>
</osm>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.osm"
            path.write_text(contents, encoding="utf-8")
            self.assertEqual(read_osm_bbox(path), (24.0, 60.0, 24.1, 60.1))

    def test_uses_nodes_when_bounds_are_missing(self):
        contents = """\
<?xml version="1.0"?>
<osm version="0.6">
  <node id="1" lat="60.1" lon="24.2"/>
  <node id="2" lat="60.0" lon="24.1"/>
</osm>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.osm"
            path.write_text(contents, encoding="utf-8")
            self.assertEqual(read_osm_bbox(path), (24.1, 60.0, 24.2, 60.1))


class WcsRequestTests(unittest.TestCase):
    def test_projects_wgs84_bbox_and_builds_native_grid_request(self):
        projected = project_bbox((24.90, 60.17, 24.91, 60.18))
        url, width, height = build_coverage_url(
            "https://example.test/wcs",
            "avoindata:Korkeusmalli_2021_1m",
            projected,
            1.0,
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["crs"], ["EPSG:3879"])
        self.assertEqual(query["response_crs"], ["EPSG:3879"])
        self.assertEqual(query["format"], ["GeoTIFF"])
        self.assertEqual(
            query["coverage"], ["avoindata:Korkeusmalli_2021_1m"]
        )
        self.assertEqual(len(query["bbox"][0].split(",")), 4)
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    def test_builds_orthophoto_map_request_in_wms_axis_order(self):
        url, width, height = build_map_url(
            "https://example.test/wms",
            "avoindata:Ortoilmakuva",
            (25490000.0, 6670000.0, 25490500.0, 6670200.0),
            1.0,
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["service"], ["WMS"])
        self.assertEqual(query["layers"], ["avoindata:Ortoilmakuva"])
        self.assertEqual(query["crs"], ["EPSG:3879"])
        self.assertEqual(query["format"], ["image/png"])
        self.assertEqual(
            query["bbox"],
            ["6670000.000000,25490000.000000,6670200.000000,25490500.000000"],
        )
        self.assertEqual((width, height), (500, 200))


class GeotiffConversionTests(unittest.TestCase):
    def test_creates_16_bit_png_and_excludes_nodata_from_scale(self):
        elevations = np.array(
            [
                [-32767.0, 1.5, 2.5],
                [3.5, 4.5, 5.5],
            ],
            dtype=np.float32,
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "elevation.tif"
            destination = Path(directory) / "elevation.png"
            Image.fromarray(elevations).save(source)

            minimum, maximum = convert_geotiff_to_png(source, destination)

            with Image.open(destination) as image:
                pixels = np.asarray(image)
                self.assertEqual(pixels.dtype, np.uint16)
                self.assertEqual(image.mode, "I;16")
                self.assertEqual(image.text["elevation_minimum"], "1.50")
                self.assertEqual(image.text["elevation_maximum"], "5.50")
                self.assertEqual(image.text["vertical_reference"], "N2000")

            self.assertEqual((minimum, maximum), (1.5, 5.5))
            self.assertEqual(pixels[0, 0], 0)
            self.assertEqual(pixels[0, 1], 0)
            self.assertEqual(pixels[1, 2], 65535)

    def test_writes_analyzed_elevation_range_to_sidecar(self):
        elevations = np.array(
            [[-32767.0, -2.125], [4.5, 12.876]], dtype=np.float32
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "elevation.tif"
            sidecar = Path(directory) / "elevation.txt"
            Image.fromarray(elevations).save(source)

            _, _, minimum, maximum = analyze_geotiff(source)
            write_elevation_sidecar(
                sidecar,
                minimum,
                maximum,
                (24.882188, 60.156222, 24.886565, 60.157985),
            )

            self.assertEqual(
                sidecar.read_text(encoding="utf-8"),
                (
                    "elevation_minimum=-2.13\n"
                    "elevation_maximum=12.88\n"
                    "units=metres\n"
                    "vertical_reference=N2000\n"
                    "bounding_box_crs=EPSG:4326\n"
                    "min_lon=24.882188\n"
                    "min_lat=60.156222\n"
                    "max_lon=24.886565\n"
                    "max_lat=60.157985\n"
                ),
            )

    def test_rounds_analyzed_range_to_centimetres(self):
        elevations = np.array(
            [[1.234, 2.345], [3.456, 4.565]], dtype=np.float64
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "elevation.tif"
            Image.fromarray(elevations).save(source)

            _, _, minimum, maximum = analyze_geotiff(source)

            self.assertEqual((minimum, maximum), (1.23, 4.57))

    def test_rejects_raster_without_valid_elevations(self):
        elevations = np.full((2, 2), -32767.0, dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "elevation.tif"
            Image.fromarray(elevations).save(source)

            with self.assertRaisesRegex(ValueError, "no valid pixels"):
                convert_geotiff_to_png(
                    source, Path(directory) / "elevation.png"
                )


if __name__ == "__main__":
    unittest.main()
