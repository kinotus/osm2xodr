import tempfile
import unittest
from pathlib import Path

from PIL import Image, PngImagePlugin

from main import create_parser, resolve_height_range, resolve_topography


class TopographyResolutionTests(unittest.TestCase):
    def setUp(self):
        self.parser = create_parser()

    def test_batch_defaults_to_data_osm(self):
        args = self.parser.parse_args(["--batch"])
        self.assertEqual(args.batch, Path("data") / "osm")

    def test_uses_png_beside_osm_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "map.osm"
            source.touch()
            image = source.with_name("map_elevation.png")
            image.touch()

            args = self.parser.parse_args(["--batch", directory])
            self.assertEqual(resolve_topography(source, args), image)

    def test_supports_legacy_same_name_png(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "map.osm"
            source.touch()
            image = source.with_suffix(".png")
            image.touch()

            args = self.parser.parse_args(["--batch", directory])
            self.assertEqual(resolve_topography(source, args), image)

    def test_reads_height_range_from_png_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "map.png"
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("elevation_minimum", "-3.5")
            metadata.add_text("elevation_maximum", "21.25")
            Image.new("I;16", (1, 1)).save(image, pnginfo=metadata)
            args = self.parser.parse_args(["--batch", directory])

            self.assertEqual(resolve_height_range(image, args), (-3.5, 21.25))

    def test_cli_height_values_override_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "map.png"
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("elevation_minimum", "-3.5")
            metadata.add_text("elevation_maximum", "21.25")
            Image.new("I;16", (1, 1)).save(image, pnginfo=metadata)
            args = self.parser.parse_args(
                ["--batch", directory, "--minimum-height", "10"]
            )

            self.assertEqual(resolve_height_range(image, args), (10.0, 21.25))

    def test_no_topography_disables_automatic_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "map.osm"
            source.touch()
            source.with_suffix(".png").touch()
            args = self.parser.parse_args(
                ["--batch", directory, "--no-topography"]
            )

            self.assertIsNone(resolve_topography(source, args))


if __name__ == "__main__":
    unittest.main()
