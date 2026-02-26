"""
Google Cloud Storage operations for canvas snapshots.

Bucket layout:
    sona-canvases/
        snapshots/{session_id}/{timestamp_iso}.png

The storage Client is synchronous — all uploads are offloaded to a thread
via asyncio.to_thread() to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from google.cloud import storage  # type: ignore[import-untyped]
from google.cloud.storage import Client as GCSClient

from gcp_auth import load_auth_config
from models import CanvasSnapshot

logger = logging.getLogger(__name__)

_storage_client: GCSClient | None = None

DEFAULT_GCS_BUCKET = "sona-canvases"


# ─── Client lifecycle ─────────────────────────────────────────────────────────

def init_storage_client() -> GCSClient:
    """Instantiate and store the GCS Client. Called once during lifespan startup."""
    global _storage_client
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    bucket_name = os.environ.get("GCS_BUCKET", DEFAULT_GCS_BUCKET)
    auth = load_auth_config()

    _storage_client = storage.Client(
        project=project_id,
        credentials=auth.credentials,
    )
    logger.info(
        "GCS Client initialised (project=%s, bucket=%s, auth=%s)",
        project_id,
        bucket_name,
        auth.source,
    )
    return _storage_client


def get_storage_client() -> GCSClient:
    """Return the module-level GCS client. Raises RuntimeError if not initialised."""
    if _storage_client is None:
        raise RuntimeError(
            "GCS client not initialised. "
            "Ensure init_storage_client() is called during lifespan startup."
        )
    return _storage_client


def close_storage_client() -> None:
    """Close the GCS Client (synchronous)."""
    global _storage_client
    if _storage_client is not None:
        _storage_client.close()
        _storage_client = None
        logger.info("GCS Client closed")


# ─── Upload ───────────────────────────────────────────────────────────────────

def _upload_png_sync(
    session_id: str,
    png_bytes: bytes,
    bucket_name: str,
) -> tuple[str, str]:
    """
    Synchronous GCS upload — runs in a thread pool via asyncio.to_thread().
    Returns (gcs_path, public_url).
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    gcs_path = f"snapshots/{session_id}/{timestamp}.png"

    blob = bucket.blob(gcs_path)
    blob.upload_from_string(png_bytes, content_type="image/png")
    # Do not use object ACLs. Most production buckets use Uniform
    # Bucket-Level Access, where legacy ACL operations are rejected.
    public_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"

    logger.info("Canvas snapshot uploaded: session=%s path=%s", session_id, gcs_path)
    return gcs_path, public_url


async def upload_canvas_snapshot(
    session_id: str,
    png_bytes: bytes,
) -> CanvasSnapshot:
    """
    Upload PNG bytes to GCS and return a CanvasSnapshot.

    The synchronous GCS upload is offloaded to a thread pool via
    asyncio.to_thread() to avoid blocking the FastAPI event loop.
    """
    bucket_name = os.environ.get("GCS_BUCKET", DEFAULT_GCS_BUCKET)

    gcs_path, public_url = await asyncio.to_thread(
        _upload_png_sync, session_id, png_bytes, bucket_name
    )

    return CanvasSnapshot(
        gcs_path=gcs_path,
        public_url=public_url,
    )
