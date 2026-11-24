import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

from prepare_data import (
    build_coverage_url,
    convert_geotiff_to_png,
    project_bbox,
    read_osm_bbox,
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
                self.assertEqual(image.text["elevation_minimum"], "1.5")
                self.assertEqual(image.text["elevation_maximum"], "5.5")
                self.assertEqual(image.text["vertical_reference"], "N2000")

            self.assertEqual((minimum, maximum), (1.5, 5.5))
            self.assertEqual(pixels[0, 0], 0)
            self.assertEqual(pixels[0, 1], 0)
            self.assertEqual(pixels[1, 2], 65535)

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
