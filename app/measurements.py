"""Measurement calculation.

  Polygon / MultiPolygon   -> area (m²)
  LineString / MultiLineString -> length (m)
  Point / MultiPoint       -> no measurement (None, documented)
  anything else            -> None, graceful note instead of a crash

Every measurement is taken on the geometry reprojected to its centroid's
UTM zone (see app/crs.py) -- never in degrees.
"""

from __future__ import annotations

from shapely import make_valid

from .crs import to_projected
from .models import Feature, Measurement

_AREA_TYPES = {"Polygon", "MultiPolygon"}
_LENGTH_TYPES = {"LineString", "MultiLineString"}
_POINT_TYPES = {"Point", "MultiPoint"}


def measure(feature: Feature) -> Measurement:
    geom = feature.geometry
    base = dict(feature_id=feature.id, geometry_type=feature.geometry_type)

    if geom is None or geom.is_empty:
        return Measurement(**base, measurement_type=None, value=None,
                           unit=None, projected_crs=None,
                           note="empty or missing geometry; nothing to measure")

    gtype = geom.geom_type
    if gtype in _POINT_TYPES:
        return Measurement(**base, measurement_type=None, value=None,
                           unit=None, projected_crs=None,
                           note="no measurement required for points")

    if gtype in _AREA_TYPES:
        mtype, unit = "area", "m²"
    elif gtype in _LENGTH_TYPES:
        mtype, unit = "length", "m"
    else:
        # Graceful: unsupported geometry types yield a null measurement,
        # never an exception.
        return Measurement(**base, measurement_type=None, value=None,
                           unit=None, projected_crs=None,
                           note=f"unsupported geometry type for measurement: {gtype}")

    valid = geom if geom.is_valid else make_valid(geom)
    projected, projected_crs = to_projected(valid, feature.crs)
    value = projected.area if mtype == "area" else projected.length
    return Measurement(**base, measurement_type=mtype, value=value,
                       unit=unit, projected_crs=projected_crs)
