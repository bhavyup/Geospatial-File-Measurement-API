"""Generate examples/sample.kml and examples/sample_shapefile.zip for the README."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))

from fixtures import SAMPLE_KML, build_shapefile_zip  # noqa: E402

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "sample.kml"), "wb") as fh:
    fh.write(SAMPLE_KML)
with open(os.path.join(HERE, "sample_shapefile.zip"), "wb") as fh:
    fh.write(build_shapefile_zip())
print("examples written")
