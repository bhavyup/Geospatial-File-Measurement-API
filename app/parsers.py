"""File parsers: KML and zipped Shapefile -> list[Feature].

No GDAL, no geopandas. KML is plain XML with a fixed CRS (EPSG:4326 per the
OGC spec), so the stdlib XML parser is plenty. Shapefiles are read with
pyshp, which is pure Python.
"""

from __future__ import annotations

import io
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import shapefile  # pyshp
from shapely.geometry import LineString, Point, Polygon, shape

from .crs import DEFAULT_CRS, parse_prj_wkt
from .models import Feature


# ---------------------------------------------------------------------------
# KML
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Tag name without namespace, so KML with or without xmlns both parse."""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def _kids(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _first(el: ET.Element, path: list[str]) -> ET.Element | None:
    """Walk down child tags by local name; None if any level is missing."""
    cur: ET.Element | None = el
    for name in path:
        if cur is None:
            return None
        kids = _kids(cur, name)
        cur = kids[0] if kids else None
    return cur


def _parse_coords(text: str | None) -> list[tuple[float, float]]:
    """Parse a KML <coordinates> string. KML order is lon,lat[,alt]."""
    pts: list[tuple[float, float]] = []
    for token in (text or "").strip().split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        pts.append((float(parts[0]), float(parts[1])))
    return pts


def _placemark_properties(pm: ET.Element) -> dict:
    props: dict = {}
    name_el = _first(pm, ["name"])
    if name_el is not None and name_el.text:
        props["name"] = name_el.text.strip()
    desc_el = _first(pm, ["description"])
    if desc_el is not None and desc_el.text:
        props["description"] = desc_el.text.strip()
    for data in _kids(pm, "ExtendedData"):
        for item in list(data):
            key = item.get("name")
            val_el = _first(item, ["value"])
            val = val_el.text if val_el is not None else item.text
            if key:
                props[key] = (val or "").strip()
    for sd in [e for e in pm.iter() if _local(e.tag) == "SimpleData"]:
        if sd.get("name"):
            props[sd.get("name")] = (sd.text or "").strip()
    return props


def _element_geometry(el: ET.Element):
    """Yield shapely geometries for one geometry element."""
    tag = _local(el.tag)
    if tag == "Point":
        pts = _parse_coords(_first(el, ["coordinates"]).text if _first(el, ["coordinates"]) is not None else "")
        if pts:
            yield Point(pts[0])
    elif tag == "LineString":
        coord_el = _first(el, ["coordinates"])
        pts = _parse_coords(coord_el.text if coord_el is not None else "")
        if len(pts) >= 2:
            yield LineString(pts)
    elif tag == "Polygon":
        outer_el = _first(el, ["outerBoundaryIs", "LinearRing", "coordinates"])
        outer = _parse_coords(outer_el.text if outer_el is not None else "")
        holes = []
        for inner in _kids(el, "innerBoundaryIs"):
            ring_el = _first(inner, ["LinearRing", "coordinates"])
            ring = _parse_coords(ring_el.text if ring_el is not None else "")
            if len(ring) >= 4:
                holes.append(ring)
        if len(outer) >= 4:
            yield Polygon(outer, holes)


def _placemark_geometries(pm: ET.Element):
    """All geometries in a Placemark; MultiGeometry is flattened into parts."""
    for mg in _kids(pm, "MultiGeometry"):
        for child in mg:
            yield from _element_geometry(child)
    for tag in ("Point", "LineString", "Polygon"):
        for el in _kids(pm, tag):
            yield from _element_geometry(el)


def parse_kml(data: bytes, file_id: str) -> tuple[list[Feature], str, bool]:
    """Parse KML bytes. Returns (features, crs, crs_assumed).

    KML is always EPSG:4326 by spec, so the CRS is declared, not assumed.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid KML: {exc}") from exc

    features: list[Feature] = []
    placemarks = [el for el in root.iter() if _local(el.tag) == "Placemark"]
    for i, pm in enumerate(placemarks):
        props = _placemark_properties(pm)
        geoms = list(_placemark_geometries(pm))
        if not geoms:
            # Placemark with no parseable geometry: keep the feature so the
            # caller sees it, with a null geometry instead of crashing.
            features.append(Feature(
                id=f"{file_id}:{i}", geometry=None, geometry_type="None",
                properties=props, crs=DEFAULT_CRS,
            ))
            continue
        for j, geom in enumerate(geoms):
            fid = f"{file_id}:{i}" if len(geoms) == 1 else f"{file_id}:{i}_{j}"
            features.append(Feature(
                id=fid, geometry=geom, geometry_type=geom.geom_type,
                properties=props, crs=DEFAULT_CRS,
            ))
    if not features:
        raise ValueError("no Placemark features found in KML")
    return features, DEFAULT_CRS, False


# ---------------------------------------------------------------------------
# Shapefile (.zip)
# ---------------------------------------------------------------------------

def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract guarding against zip-slip path traversal."""
    real_dest = os.path.realpath(dest)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(dest, member))
        if target != real_dest and not target.startswith(real_dest + os.sep):
            raise ValueError(f"unsafe path in zip archive: {member!r}")
    zf.extractall(dest)


def parse_shapefile_zip(data: bytes, file_id: str) -> tuple[list[Feature], str, bool]:
    """Parse a .zip containing a Shapefile. Returns (features, crs, crs_assumed)."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("not a valid zip archive")

    tmpdir = tempfile.mkdtemp(prefix="shp_")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        _safe_extract(zf, tmpdir)

    shp_candidates = sorted(
        os.path.join(root, f)
        for root, _, files in os.walk(tmpdir)
        for f in files if f.lower().endswith(".shp")
    )
    if not shp_candidates:
        raise ValueError("zip archive contains no .shp file")

    shp_path = shp_candidates[0]
    base, _ = os.path.splitext(shp_path)

    crs, assumed = DEFAULT_CRS, True
    prj_path = base + ".prj"
    if os.path.exists(prj_path):
        with open(prj_path, encoding="utf-8", errors="replace") as fh:
            crs, assumed = parse_prj_wkt(fh.read())

    try:
        reader = shapefile.Reader(shp_path)
    except Exception as exc:
        raise ValueError(f"cannot read shapefile: {exc}") from exc

    field_names = [f[0] for f in reader.fields[1:]]  # first entry is DeletionFlag
    features: list[Feature] = []
    for i, sr in enumerate(reader.iterShapeRecords()):
        try:
            geom = shape(sr.shape.__geo_interface__)
        except Exception:
            geom = None
        props = dict(zip(field_names, list(sr.record)))
        features.append(Feature(
            id=f"{file_id}:{i}",
            geometry=geom,
            geometry_type=geom.geom_type if geom is not None else "None",
            properties=props,
            crs=crs,
        ))
    if not features:
        raise ValueError("shapefile contains no features")
    return features, crs, assumed
