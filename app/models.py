"""Domain models for the geospatial file measurement service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from shapely.geometry.base import BaseGeometry


@dataclass
class Feature:
    """A single geospatial feature extracted from an uploaded file."""

    id: str                      # stable id: "<file_id>:<index>" (or "<file_id>:<index>_<part>")
    geometry: Optional[BaseGeometry]
    geometry_type: str           # e.g. "Polygon", "LineString", "Point", "GeometryCollection"
    properties: dict[str, Any]   # attributes from the source file
    crs: str                     # source CRS, e.g. "EPSG:4326"


@dataclass
class Measurement:
    """Measurement result for one feature. value is None when not measurable."""

    feature_id: str
    geometry_type: str
    measurement_type: Optional[str]  # "area" | "length" | None
    value: Optional[float]           # square metres for area, metres for length
    unit: Optional[str]              # "m²" | "m" | None
    projected_crs: Optional[str]     # EPSG code the geometry was measured in
    note: Optional[str] = None       # explains a null value (point, unsupported, empty...)


@dataclass
class StoredFile:
    """Everything we keep about one uploaded file."""

    id: str
    filename: str
    source_crs: str
    crs_assumed: bool            # True when the file carried no CRS metadata
    status: str                  # "COMPLETED" (uploads are processed synchronously)
    features: list[Feature] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)

    @property
    def feature_count(self) -> int:
        return len(self.features)
