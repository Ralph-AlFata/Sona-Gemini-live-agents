"""
Firestore-backed element store for the Drawing Command Service.

Collection layout:
    canvas_sessions/{session_id}                   → session metadata doc
    canvas_sessions/{session_id}/elements/{element_id} → individual element docs

Each element document schema:
    {
        "element_id": "el_...",
        "element_type": "shape" | "text" | "freehand" | "highlight",
        "payload": { ... },        # JSON-serialisable drawing data
        "bbox": { "x": f, "y": f, "width": f, "height": f }
    }

The module holds a single AsyncClient instance initialised during app lifespan.
Access it via get_firestore_client(). Spatial queries (e.g. erase region)
read all elements and filter in memory — Firestore has no native bbox queries.

Activate with USE_FIRESTORE=true in .env.
"""

from __future__ import annotations

import logging
import os

from google.cloud.firestore_v1.async_client import AsyncClient  # type: ignore[import-untyped]

from config import settings
from gcp_auth import load_auth_config
from store import BBox, StoredElement

logger = logging.getLogger(__name__)

_firestore_client: AsyncClient | None = None

SESSION_COLLECTION = "canvas_sessions"
ELEMENT_SUBCOLLECTION = "elements"


# ─── Client lifecycle ─────────────────────────────────────────────────────────


def init_firestore_client() -> AsyncClient:
    """Instantiate and store the Firestore AsyncClient. Called once during lifespan startup."""
    global _firestore_client
    project_id = (
        os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or settings.google_cloud_project.strip()
    )
    if not project_id:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is required when USE_FIRESTORE=true"
        )
    database_id = (
        os.environ.get("FIRESTORE_DATABASE", "").strip()
        or settings.firestore_database
        or "(default)"
    )
    auth = load_auth_config()

    _firestore_client = AsyncClient(
        project=project_id,
        database=database_id,
        credentials=auth.credentials,
    )
    logger.info(
        "Firestore AsyncClient initialised (project=%s, database=%s, auth=%s)",
        project_id,
        database_id,
        auth.source,
    )
    return _firestore_client


def get_firestore_client() -> AsyncClient:
    """Return the module-level Firestore client. Raises RuntimeError if not initialised."""
    if _firestore_client is None:
        raise RuntimeError(
            "Firestore client not initialised. "
            "Ensure init_firestore_client() is called during lifespan startup."
        )
    return _firestore_client


async def close_firestore_client() -> None:
    """Close the Firestore AsyncClient. Called once during lifespan shutdown."""
    global _firestore_client
    if _firestore_client is not None:
        await _firestore_client.close()
        _firestore_client = None
        logger.info("Firestore AsyncClient closed")


# ─── Serialisation helpers ────────────────────────────────────────────────────


def _element_to_doc(element: StoredElement) -> dict:
    return {
        "element_id": element.element_id,
        "element_type": element.element_type,
        "payload": element.payload,
        "bbox": {
            "x": element.bbox.x,
            "y": element.bbox.y,
            "width": element.bbox.width,
            "height": element.bbox.height,
        },
    }


def _doc_to_element(doc: dict) -> StoredElement:
    bbox_raw = doc.get("bbox", {})
    return StoredElement(
        element_id=str(doc["element_id"]),
        element_type=str(doc["element_type"]),
        payload=dict(doc.get("payload", {})),
        bbox=BBox(
            x=float(bbox_raw.get("x", 0.0)),
            y=float(bbox_raw.get("y", 0.0)),
            width=float(bbox_raw.get("width", 0.0)),
            height=float(bbox_raw.get("height", 0.0)),
        ),
    )


# ─── FirestoreElementStore ────────────────────────────────────────────────────


class FirestoreElementStore:
    """
    Firestore-backed implementation of the ElementStore protocol.

    Reads load all sub-collection documents into memory. Writes are
    individual document sets/deletes. Spatial queries (erase region)
    filter the in-memory snapshot returned by get_all_elements().
    """

    async def get_all_elements(self, session_id: str) -> dict[str, StoredElement]:
        """Read all element documents for a session from Firestore."""
        client = get_firestore_client()
        col_ref = (
            client.collection(SESSION_COLLECTION)
            .document(session_id)
            .collection(ELEMENT_SUBCOLLECTION)
        )
        docs = col_ref.stream()
        result: dict[str, StoredElement] = {}
        async for doc in docs:
            raw = doc.to_dict()
            if raw:
                element = _doc_to_element(raw)
                result[element.element_id] = element
        logger.debug(
            "Loaded %d elements for session %s from Firestore",
            len(result),
            session_id,
        )
        return result

    async def put_element(self, session_id: str, element: StoredElement) -> None:
        """Write or overwrite a single element document in Firestore."""
        client = get_firestore_client()
        doc_ref = (
            client.collection(SESSION_COLLECTION)
            .document(session_id)
            .collection(ELEMENT_SUBCOLLECTION)
            .document(element.element_id)
        )
        await doc_ref.set(_element_to_doc(element))
        logger.debug(
            "Persisted element %s (type=%s) for session %s",
            element.element_id,
            element.element_type,
            session_id,
        )

    async def delete_element(self, session_id: str, element_id: str) -> None:
        """Delete a single element document from Firestore. No-op if not found."""
        client = get_firestore_client()
        doc_ref = (
            client.collection(SESSION_COLLECTION)
            .document(session_id)
            .collection(ELEMENT_SUBCOLLECTION)
            .document(element_id)
        )
        await doc_ref.delete()
        logger.debug("Deleted element %s from session %s", element_id, session_id)

    async def clear_session(self, session_id: str) -> None:
        """Batch-delete all element documents for a session."""
        client = get_firestore_client()
        col_ref = (
            client.collection(SESSION_COLLECTION)
            .document(session_id)
            .collection(ELEMENT_SUBCOLLECTION)
        )
        # Firestore batch deletes in chunks of 500
        batch = client.batch()
        count = 0
        async for doc in col_ref.stream():
            batch.delete(doc.reference)
            count += 1
            if count % 500 == 0:
                await batch.commit()
                batch = client.batch()
        if count % 500 != 0:
            await batch.commit()
        logger.info("Cleared %d elements for session %s", count, session_id)
