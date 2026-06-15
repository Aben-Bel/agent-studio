"""Data plane: upload files, connect databases, run the ingestion pipeline."""
import os
import tempfile

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel

from core import pipeline
from core.schemas import ConnectDbRequest
from connectors import datastore
from connectors.ingest import ingest
from connectors.s3 import s3

router = APIRouter()


@router.post("/upload")
async def upload(files: list[UploadFile] = File(default=None),
                 file: UploadFile = File(default=None)):
    """Ingest one or many files in a single request. CSVs each become their own
    SQL table; PDF/TXT/MD are chunked + embedded into the RAG store. Accepts the
    multi-file field `files` (preferred) and a single `file` for compatibility."""
    incoming = list(files or [])
    if file is not None:
        incoming.append(file)

    results = []
    for uf in incoming:
        suffix = os.path.splitext(uf.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(await uf.read())
            path = f.name
        try:
            results.append({"name": uf.filename, **ingest(path, uf.filename)})
        except Exception as e:
            results.append({"name": uf.filename, "kind": "error", "reason": str(e)})
        finally:
            os.unlink(path)
    return {"results": results}


class PresignRequest(BaseModel):
    filename: str
    content_type: str | None = None


class S3Ref(BaseModel):
    key: str   # key (or full s3:// / https URL) returned by /uploads/presign


@router.post("/uploads/presign")
def presign_upload(req: PresignRequest):
    """Hand the browser a presigned URL so it can PUT a file straight to S3
    (bytes never pass through the backend). The browser sends `key` back to
    /ingest-s3 for the backend to pick up."""
    return s3.presign_put(req.filename, req.content_type)


@router.post("/ingest-s3")
def ingest_s3(ref: S3Ref):
    """Pick up a previously-uploaded S3 object by key/link and run it through the
    same ingest pipeline as a direct upload."""
    bucket, key = s3.parse(ref.key)
    try:
        path = s3.download_to_tmp(ref.key)
    except Exception as e:
        return {"name": os.path.basename(key), "kind": "error",
                "reason": f"could not fetch s3 object: {e}"}
    try:
        return {"name": os.path.basename(key), "key": key, **ingest(path, key)}
    except Exception as e:
        return {"name": os.path.basename(key), "kind": "error", "reason": str(e)}
    finally:
        os.unlink(path)


@router.post("/connect-db")
def connect_db(req: ConnectDbRequest):
    """Connect an external database by URL (e.g. a Postgres process-parameter DB).
    Validated, introspected, and registered as a queryable data source."""
    try:
        return {"connected": True, **datastore.connect_db(req.url, req.name)}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/sources")
def sources():
    """Every connected data source and the tables inside it: the local CSV store
    plus any databases added via /connect-db or DATABASE_URL."""
    return {"sources": datastore.list_sources()}


@router.post("/process")
def process():
    """Run the ingestion pipeline over any pending uploads (the sweep). Idempotent."""
    return {"processed": pipeline.run_pending()}


@router.get("/process/status")
def process_status():
    """Pipeline status: how many documents are pending vs done, and the stages."""
    return pipeline.status()
