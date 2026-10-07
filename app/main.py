"""FastAPI application: upload, file info, measurements."""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from shapely.geometry import mapping

from . import store
from .measurements import measure
from .models import StoredFile
from .parsers import parse_kml, parse_shapefile_zip

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a Shapefile (.zip) or KML, get per-feature measurements.",
    version="1.0.0",
)


def _file_info_payload(rec: StoredFile) -> dict:
    return {
        "id": rec.id,
        "filename": rec.filename,
        "feature_count": rec.feature_count,
        "crs": rec.source_crs,
        "crs_assumed": rec.crs_assumed,
        "status": rec.status,
    }


def _measurement_payload(m, rec: StoredFile) -> dict:
    feature = next(f for f in rec.features if f.id == m.feature_id)
    return {
        "feature_id": m.feature_id,
        "geometry_type": m.geometry_type,
        "geometry": mapping(feature.geometry) if feature.geometry is not None else None,
        "crs": feature.crs,
        "properties": feature.properties,
        "measurement": (
            {
                "type": m.measurement_type,
                "value": m.value,
                "unit": m.unit,
                "projected_crs": m.projected_crs,
            }
            if m.measurement_type
            else None
        ),
        "note": m.note,
    }


@app.get("/api/files/", summary="List uploaded files")
def list_files():
    return [_file_info_payload(r) for r in store.list_all()]


@app.post("/api/files/", status_code=201, summary="Upload and process a geospatial file")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 50 MB)")

    name = filename.lower()
    try:
        file_id = store.new_id()
        if name.endswith(".zip"):
            features, crs, assumed = parse_shapefile_zip(data, file_id)
        elif name.endswith(".kml"):
            features, crs, assumed = parse_kml(data, file_id)
        else:
            raise HTTPException(
                status_code=422,
                detail="unsupported file type: expected a .zip containing a Shapefile or a .kml file",
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    measurements = [measure(f) for f in features]
    store.save_upload(file_id, filename, data)
    rec = StoredFile(
        id=file_id, filename=filename, source_crs=crs,
        crs_assumed=assumed, status="COMPLETED",
        features=features, measurements=measurements,
    )
    store.put(rec)
    return JSONResponse(status_code=201, content=_file_info_payload(rec))


@app.get("/api/files/{file_id}/", summary="File information")
def file_info(file_id: str):
    rec = store.get(file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="file not found")
    return _file_info_payload(rec)


@app.get("/api/files/{file_id}/measurements/", summary="Feature measurements")
def file_measurements(file_id: str):
    rec = store.get(file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="file not found")
    return [_measurement_payload(m, rec) for m in rec.measurements]
