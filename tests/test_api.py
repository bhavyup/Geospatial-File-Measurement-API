"""End-to-end tests: upload -> file info -> measurements, plus edge cases."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from pyproj import Geod
from shapely.geometry import GeometryCollection, Point, Polygon

from app import store
from app.crs import utm_epsg_for
from app.main import app
from app.measurements import measure
from app.models import Feature

from .fixtures import SAMPLE_KML, build_shapefile_zip

client = TestClient(app)
GEOD = Geod(ellps="WGS84")


@pytest.fixture(autouse=True)
def clean_store():
    store._files.clear()
    yield
    store._files.clear()


def _upload(filename: str, data: bytes):
    return client.post("/api/files/", files={"file": (filename, data)})


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_kml_full_flow():
    r = _upload("sample.kml", SAMPLE_KML)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["filename"] == "sample.kml"
    assert info["feature_count"] == 3
    assert info["crs"] == "EPSG:4326"
    assert info["crs_assumed"] is False
    assert info["status"] == "COMPLETED"
    fid = info["id"]

    r = client.get(f"/api/files/{fid}/")
    assert r.status_code == 200
    assert r.json()["id"] == fid

    r = client.get(f"/api/files/{fid}/measurements/")
    assert r.status_code == 200
    ms = {m["feature_id"]: m for m in r.json()}
    assert len(ms) == 3

    poly = next(m for m in ms.values() if m["geometry_type"] == "Polygon")
    assert poly["geometry"]["type"] == "Polygon"
    assert poly["crs"] == "EPSG:4326"
    assert poly["properties"]["name"] == "one-degree-square"
    assert poly["properties"]["landuse"] == "survey"
    assert poly["measurement"]["type"] == "area"
    assert poly["measurement"]["unit"] == "m²"
    assert poly["measurement"]["projected_crs"] == "EPSG:32643"  # UTM zone of lon 77.5
    # independent geodesic reference: must NOT be degree-math
    expected, _ = GEOD.geometry_area_perimeter(
        Polygon([(77, 8), (78, 8), (78, 9), (77, 9), (77, 8)]))
    assert abs(poly["measurement"]["value"] - abs(expected)) / abs(expected) < 0.005

    line = next(m for m in ms.values() if m["geometry_type"] == "LineString")
    assert line["measurement"]["type"] == "length"
    assert line["measurement"]["unit"] == "m"
    expected_len = GEOD.line_length([77, 78], [8.5, 8.5])
    assert abs(line["measurement"]["value"] - expected_len) / expected_len < 0.005

    point = next(m for m in ms.values() if m["geometry_type"] == "Point")
    assert point["measurement"] is None
    assert "point" in point["note"].lower()


def test_shapefile_zip_full_flow():
    data = build_shapefile_zip()
    r = _upload("sample.zip", data)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["feature_count"] == 2  # two polygons in sample.shp
    assert info["crs"] == "EPSG:4326"
    assert info["crs_assumed"] is False  # .prj was present
    fid = info["id"]

    r = client.get(f"/api/files/{fid}/measurements/")
    assert r.status_code == 200
    ms = r.json()
    assert len(ms) == 2
    names = {m["properties"]["name"] for m in ms}
    assert names == {"one-degree-square", "small-triangle"}
    for m in ms:
        assert m["geometry_type"] == "Polygon"
        assert m["measurement"]["type"] == "area"
        assert m["measurement"]["value"] > 0


def test_list_files():
    _upload("a.kml", SAMPLE_KML)
    _upload("b.kml", SAMPLE_KML)
    r = client.get("/api/files/")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# Edge cases: graceful, never crashing
# ---------------------------------------------------------------------------

def test_kml_without_namespace_parses():
    # some exporters omit the xmlns; tags are matched by local name
    raw = SAMPLE_KML.replace(b' xmlns="http://www.opengis.net/kml/2.2"', b"")
    r = _upload("nonamespace.kml", raw)
    assert r.status_code == 201, r.text
    assert r.json()["feature_count"] == 3


def test_unsupported_extension_rejected():
    r = _upload("data.geojson", b"{}")
    assert r.status_code == 422


def test_invalid_kml_rejected():
    r = _upload("bad.kml", b"this is not xml <")
    assert r.status_code == 422


def test_kml_without_placemarks_rejected():
    r = _upload("empty.kml",
                b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
    assert r.status_code == 422


def test_zip_without_shapefile_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hello")
    r = _upload("empty.zip", buf.getvalue())
    assert r.status_code == 422


def test_not_a_zip_rejected():
    r = _upload("fake.zip", b"definitely not a zip")
    assert r.status_code == 422


def test_unknown_file_id_404():
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404


def test_unsupported_geometry_type_is_graceful():
    gc = GeometryCollection([Point(0, 0)])
    f = Feature(id="x:0", geometry=gc, geometry_type="GeometryCollection",
                properties={}, crs="EPSG:4326")
    m = measure(f)
    assert m.value is None and m.measurement_type is None
    assert "unsupported" in (m.note or "").lower()


def test_empty_geometry_is_graceful():
    f = Feature(id="x:0", geometry=Point(), geometry_type="Point",
                properties={}, crs="EPSG:4326")
    m = measure(f)
    assert m.value is None


def test_utm_zone_selection():
    assert utm_epsg_for(77.5, 8.5) == 32643   # India, northern hemisphere
    assert utm_epsg_for(-73.9, -33.0) == 32718  # southern hemisphere
    assert utm_epsg_for(179.9, 0.0) == 32660
