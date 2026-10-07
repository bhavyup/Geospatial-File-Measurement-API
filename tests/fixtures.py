"""Shared fixtures: a sample KML and a sample zipped Shapefile, built in code."""

from __future__ import annotations

import io
import os
import tempfile
import zipfile

import shapefile  # pyshp

SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>sample</name>
    <Placemark>
      <name>one-degree-square</name>
      <ExtendedData>
        <Data name="landuse"><value>survey</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          77,8,0 78,8,0 78,9,0 77,9,0 77,8,0
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>one-degree-line</name>
      <LineString><coordinates>77,8.5,0 78,8.5,0</coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>a-point</name>
      <Point><coordinates>77.5,8.5,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
""".encode()


def build_shapefile_zip() -> bytes:
    """Build a small shapefile (polygon + line + point) and return it zipped."""
    tmpdir = tempfile.mkdtemp(prefix="sample_shp_")
    base = os.path.join(tmpdir, "sample")

    with shapefile.Writer(base, shapeType=shapefile.POLYGON) as w:
        w.field("name", "C", size=50)
        w.field("landuse", "C", size=50)
        # rings written clockwise = exterior rings per the shapefile spec
        w.poly([[[77, 8], [77, 9], [78, 9], [78, 8], [77, 8]]])
        w.record("one-degree-square", "survey")
        w.poly([[[77.1, 8.1], [77.15, 8.2], [77.2, 8.1], [77.1, 8.1]]])
        w.record("small-triangle", "survey")

    with shapefile.Writer(base + "_line", shapeType=shapefile.POLYLINE) as w:
        w.field("name", "C", size=50)
        w.line([[[77, 8.5], [78, 8.5]]])
        w.record("one-degree-line")

    with shapefile.Writer(base + "_pt", shapeType=shapefile.POINT) as w:
        w.field("name", "C", size=50)
        w.point(77.5, 8.5)
        w.record("a-point")

    # EPSG:4326 WKT so the .prj path is exercised
    prj_wkt = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
        'AUTHORITY["EPSG","4326"]]'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for suffix in ("", "_line", "_pt"):
            for ext in (".shp", ".shx", ".dbf"):
                zf.write(base + suffix + ext, f"sample{suffix}{ext}")
        zf.writestr("sample.prj", prj_wkt)
    return buf.getvalue()
