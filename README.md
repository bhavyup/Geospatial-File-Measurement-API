# Geospatial File Measurement API

I built a small backend service that takes a geospatial file — a shapefile
zipped up, or a KML — and returns measurements for every feature inside it.
Polygons get an area, linestrings get a length, points get nothing (as
specified). The one thing I was careful about: measurements are always done
in a proper projected coordinate system, never in raw lat/lon degrees.

Stack: **FastAPI** + **Shapely 2** + **pyproj** + **pyshp**. I deliberately
avoided GDAL/geopandas — everything here installs with a plain `pip install`,
no system libraries.

---

## Setup

You need Python 3.10+.

```bash
git clone https://github.com/bhavyup/Geospatial-File-Measurement-API.git
cd Geospatial-File-Measurement-API

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Docs UI: http://127.0.0.1:8000/docs

Tests:

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

There are sample files in `examples/` if you want to try it immediately:
`sample.kml` and `sample_shapefile.zip` (a 1°×1° square near the equator,
a 1° line, and a point).

---

## API

### `POST /api/files/` — upload and process

Multipart upload. Accepts `.zip` (must contain a shapefile) or `.kml`.
Files are processed right away, so the response is a `201` with the file
record. Bad files get a `422`, anything over 50 MB gets a `413`.

```bash
curl -X POST http://127.0.0.1:8000/api/files/ \
  -F "file=@examples/sample.kml"
```

```json
{
  "id": "4eb47fc083f5",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "crs_assumed": false,
  "status": "COMPLETED"
}
```

### `GET /api/files/{id}/` — file info

```bash
curl http://127.0.0.1:8000/api/files/4eb47fc083f5/
```

Same shape as above. Unknown id → `404`.

### `GET /api/files/{id}/measurements/` — the actual measurements

One entry per feature: its id, geometry type, the geometry itself (GeoJSON),
source CRS, attributes, and the measurement.

```bash
curl http://127.0.0.1:8000/api/files/4eb47fc083f5/measurements/
```

```json
[
  {
    "feature_id": "4eb47fc083f5:0",
    "geometry_type": "Polygon",
    "geometry": {"type": "Polygon", "coordinates": [[[77.0, 8.0], ...]]},
    "crs": "EPSG:4326",
    "properties": {"name": "one-degree-square", "landuse": "survey"},
    "measurement": {
      "type": "area",
      "value": 12190663855.4,
      "unit": "m²",
      "projected_crs": "EPSG:32643"
    },
    "note": null
  },
  {
    "feature_id": "4eb47fc083f5:1",
    "geometry_type": "LineString",
    "properties": {"name": "one-degree-line"},
    "measurement": {"type": "length", "value": 110165.3, "unit": "m",
                    "projected_crs": "EPSG:32643"},
    "note": null
  },
  {
    "feature_id": "4eb47fc083f5:2",
    "geometry_type": "Point",
    "properties": {"name": "a-point"},
    "measurement": null,
    "note": "no measurement required for points"
  }
]
```

There's also a `GET /api/files/` that just lists everything uploaded so far.

---

## How it's put together

```
app/
  main.py          routes, validation, response shaping
  parsers.py       KML + zipped shapefile parsing -> Feature list
  crs.py           CRS detection, UTM zone picking, reprojection
  measurements.py  area/length per feature, graceful when it can't measure
  models.py        plain dataclasses: Feature, Measurement, StoredFile
  store.py         keeps uploads on disk, metadata in memory
tests/
  test_api.py      12 tests, end-to-end plus edge cases
  fixtures.py      builds the sample KML and shapefile zip in code
examples/          sample.kml, sample_shapefile.zip + the builder script
```

### File-processing flow

1. `POST /api/files/` checks the extension (`.zip` / `.kml`) and the size cap.
2. Then the right parser runs:
   - **KML** — I parse it with the stdlib XML parser, matching tags by local
     name so files with or without the `xmlns` both work. KML is always
     `EPSG:4326` with `lon,lat` ordering, that's in the spec, so there's
     nothing to detect. Placemark names, descriptions and `ExtendedData`
     become the feature's properties. A `MultiGeometry` gets flattened so
     each part is its own feature.
   - **Shapefile zip** — extracted to a temp dir (with a zip-slip guard),
     read with pyshp. The `.prj` WKT is parsed for the CRS; if it's missing
     or garbage I assume `EPSG:4326` and say so via `crs_assumed: true`
     rather than silently pretending.
3. Every feature is stored with its id, geometry type, geometry, CRS and
   properties. The raw upload stays on disk, metadata in the registry.

### Measurement flow

1. Look at the geometry type: polygon → area, linestring → length,
   point → skip.
2. If the geometry is invalid (self-intersecting rings happen in real files),
   repair it with `shapely.make_valid` first — measuring a broken polygon
   silently returns a wrong number, which is worse than failing.
3. Reproject to the feature's own UTM zone, read off area/length in m²/m.
4. Empty geometries or types I don't measure (like a raw GeometryCollection)
   come back as `null` with a `note` explaining why. Nothing crashes.

### CRS handling

This was the core of the assignment, so: I never do math in degrees. Every
measurable feature is reprojected to the **UTM zone of its own centroid**
(`EPSG:326xx` / `327xx`) before measuring. UTM is conformal and nearly
distortion-free inside a zone, so for normal file extents the numbers are
good to well under 0.1% — I check this in tests against an independent
geodesic computation with `pyproj.Geod`.

One honest limitation: a feature straddling a zone boundary gets measured in
its centroid's zone, which adds a small error. Polar areas and geometries
crossing the antimeridian aren't handled specially yet (see future scope).

---

## Decisions I made (and what I didn't pick)

**FastAPI, not Django.** This is a handful of JSON endpoints. FastAPI gives
me validation and OpenAPI docs with almost no scaffolding. Django would make
sense if this grew auth and an admin panel — it didn't need it.

**No geopandas/GDAL.** The number one way geospatial Python projects fail to
run is the GDAL install. pyshp plus a small KML parser cover exactly the two
required formats with pure-Python deps. Less power, far less pain.

**I wrote the KML parser by hand.** KML is simple XML with a fixed CRS —
about a hundred lines of stdlib code, zero new dependencies, fully tested.
Pulling in fastkml for that felt like overkill.

**Per-feature UTM zones.** There's no single projection that's right
everywhere, so each feature gets its own local zone. (Fun fact: doing it
geodesically with `pyproj.Geod` would actually be *more* correct globally —
but the spec explicitly asks for a projected-CRS transform, so UTM it is.)

**Synchronous processing.** Parsing is milliseconds for sane uploads; a job
queue would be operational theater at this scale. The `status` field is
already there if this ever needs to go async.

**In-memory registry + uploads on disk.** Keeps the whole thing runnable with
one command. In production I'd put metadata in Postgres/PostGIS and files in
object storage — that's the obvious next step, not something to fake here.

**Zip-slip guard + 50 MB cap.** Uploads are the attack surface; both are
cheap.

---

## Testing

`pytest tests/ -q` — 12 tests:

- full KML round trip: upload → info → measurements, with the area/length
  checked against an independent geodesic reference and the UTM zone asserted
- full shapefile-zip round trip, including `.prj` CRS detection and the
  DBF attribute mapping
- points and unsupported geometry types degrade to `null` gracefully
- invalid KML, zip-without-shapefile, non-zip bytes, wrong extension → `422`
- unknown file id → `404`; UTM zone math for both hemispheres

---

## What I learned

The big one: why you can't measure in degrees. A degree of longitude is
~111 km at the equator and ~0 km at the poles, so "square degrees" is a
meaningless unit — building the per-feature UTM reprojection made that
concrete in a way reading about it never did.

Smaller things: KML fixes its CRS in the spec while shapefiles carry theirs
in a sidecar `.prj` — two opposite philosophies of metadata. And real files
contain self-intersecting polygons, so `make_valid` before measuring isn't
optional; without it you get a confident wrong number instead of an error.

## Future scope

- Postgres + PostGIS for metadata, object storage for uploads, and a real
  job queue (Celery/RQ) with `PENDING`/`FAILED` statuses for big files
- More input formats: GeoJSON, GPX, GeoPackage
- CRS edge cases: antimeridian-safe handling, polar stereographic fallback
  past 84°, equal-area projections for continent-scale polygons
- More measurements: polygon perimeter, 3D length/area honoring Z values,
  reporting a geodesic cross-check next to the projected value
- API niceties: pagination on measurements, filtering by geometry type,
  async upload with a webhook when it's done
