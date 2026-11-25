# osm2xodr
converter for OpenStreetMaps (.osm) to OpenDrive (.xodr) format (just the drivable roads right now - you can edit the code for other osm-ways - its in the function "parseAll()").

just adjust the filenames/paths in the main.py and run it.

The requirements are osmread, numpy, PIL and pyproj

## Command line usage

Run the original conversion:

```shell
python main.py
```

Convert all `.osm` files in the `data/osm` directory:

```shell
python main.py --batch
```

Choose another batch directory and output directory:

```shell
python main.py --batch path/to/osm-files --output-dir path/to/xodr-files
```

## Prepare Helsinki elevation data

Download the Helsinki 1 m elevation model for every `.osm` file in
`data/osm`:

```shell
python prepare_data.py
```

The script prefers the WGS84 `<bounds>` element in each OSM file and falls
back to the coordinates of its nodes. It requests the Helsinki
`avoindata:Korkeusmalli_2021_1m` coverage through WCS, transforms the extent to
the native EPSG:3879 GK25 coordinate system, and downloads the
`avoindata:Ortoilmakuva` aerial image through WMS. For example, `hietsu.osm`
produces `hietsu_elevation.tif`, `hietsu_elevation.png`,
`hietsu_elevation.txt`, and `hietsu_orto.png`.

The floating-point DEM is converted to a 16-bit elevation PNG. Its text sidecar
records the minimum and maximum valid N2000 elevation values, the units, the
vertical reference, and the WGS84 OSM bounding-box coordinates (`min_lon`,
`min_lat`, `max_lon`, `max_lat`).
These values can be used e.g. in Metromake to set the correct elevation and
coordinate ranges.

The PNG uses the full 16-bit range for valid elevations. Its
`elevation_minimum` and `elevation_maximum` metadata records the same N2000
values written to the text sidecar. Elevation limits are rounded to the
nearest centimetre. These values can be supplied as `--minimum-height` and
`--maximum-height` to a conversion. NoData pixels are excluded from that range.
The GeoTIFF remains available as the lossless, georeferenced source.

Use `--input-dir`, `--output-dir`, `--resolution`, `--coverage`, `--wms-url`, or
`--wms-layer` to override the defaults. Existing output files are replaced
after a successful download.

The source dataset is provided by the City of Helsinki through its
[open geospatial data services](https://www.hel.fi/fi/paatoksenteko-ja-hallinto/tietoa-helsingista/kartat-ja-paikkatieto/paikkatiedot-tehokayttoon/avoimet-paikkatiedot)
and [geospatial data catalogue](https://kartta.hel.fi/paikkatietohakemisto/pth/).
The [WCS endpoint](https://kartta.hel.fi/ws/geoserver/avoindata/wcs?service=WCS&request=GetCapabilities)
is the authoritative source for currently published coverages.

Convert one or more explicit inputs:

```shell
python main.py map.osm
python main.py first.osm second.osm --output-dir converted
```

For every input, batch conversions automatically use a same-name PNG stored
beside the `.osm` file. PNGs created by `prepare_data.py` contain their
elevation range in metadata, which is also read automatically. Files without a
matching PNG are converted without topography. Supply
`--topography path/to/image.png` to use the same image for every input, or use
`--no-topography` to disable automatic discovery. `--minimum-height` and
`--maximum-height` override image metadata; `--curve-radius` controls the
conversion radius.

If a topographymap is used it should be in 16bit integer format and the max/min latitudes/longitudes of the map should match the points in the osm-file.





This code was created as a part of
<p align="center"><img src="https://github.com/JHMeusener/osm2xodr/blob/master/Projekt%20und%20F%C3%B6rderlogos%20EN_28.11.2019.jpg" /></p>
