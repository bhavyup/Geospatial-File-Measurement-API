"""CRS handling: detect the source CRS, pick a projected CRS, reproject.

Strategy (documented in README under "CRS handling"):
  * Never measure in geographic (degree) coordinates.
  * Each measurable feature is reprojected to the UTM zone of its own
    centroid (EPSG:326xx north / 327xx south, WGS84 datum). UTM is conformal
    with low distortion inside a zone, so area/length measured there is
    accurate to well within 0.1% for typical file extents.
  * Features spanning a zone boundary are measured in the zone of their
    centroid; the (small) distortion is accepted and documented.
"""

from __future__ import annotations

import math

import numpy as np
from pyproj import CRS, Transformer
from shapely import transform as shp_transform
from shapely.geometry.base import BaseGeometry

DEFAULT_CRS = "EPSG:4326"


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def to_projected(geom: BaseGeometry, source_crs: str) -> tuple[BaseGeometry, str]:
    """Reproject ``geom`` to its centroid's UTM zone.

    Returns (projected_geometry, "EPSG:xxxxx").
    """
    centroid = geom.centroid
    epsg = utm_epsg_for(centroid.x, centroid.y)
    transformer = Transformer.from_crs(
        CRS.from_user_input(source_crs),
        CRS.from_epsg(epsg),
        always_xy=True,
    )

    def _apply(coords: np.ndarray) -> np.ndarray:
        # shapely.transform hands us an (N, 2|3) array; keep any Z untouched.
        xs, ys = transformer.transform(coords[:, 0], coords[:, 1])
        out = np.empty_like(coords, dtype=float)
        out[:, 0], out[:, 1] = xs, ys
        if coords.shape[1] > 2:
            out[:, 2:] = coords[:, 2:]
        return out

    return shp_transform(geom, _apply), f"EPSG:{epsg}"


def parse_prj_wkt(wkt: str) -> tuple[str, bool]:
    """Parse a shapefile .prj WKT string.

    Returns (crs_string, assumed). Falls back to EPSG:4326 when the WKT is
    missing or unparseable, flagging the assumption so callers can surface it.
    """
    if not wkt or not wkt.strip():
        return DEFAULT_CRS, True
    try:
        crs = CRS.from_wkt(wkt)
        return crs.to_string(), False
    except Exception:
        return DEFAULT_CRS, True
