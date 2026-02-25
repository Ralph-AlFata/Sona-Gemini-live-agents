"""
Firestore async client and session CRUD operations.

Collection layout:
    sessions/{session_id}   →  Session document (flat doc, no sub-collections)

The module holds a single AsyncClient instance initialised during app lifespan.
Access it via get_firestore_client().
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.async_client import AsyncClient  # type: ignore[import-untyped]

from gcp_auth import load_auth_config
from models import CanvasSnapshot, ConversationTurn, Session, SessionCreate

logger = logging.getLogger(__name__)

_firestore_client: AsyncClient | None = None

COLLECTION_NAME = "sessions"


# ─── Client lifecycle ─────────────────────────────────────────────────────────

def init_firestore_client() -> AsyncClient:
    """Instantiate and store the Firestore AsyncClient. Called once during lifespan startup."""
    global _firestore_client
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    database_id = os.environ.get("FIRESTORE_DATABASE", "(default)")
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


# ─── CRUD operations ──────────────────────────────────────────────────────────

async def create_session(payload: SessionCreate) -> Session:
    """Create a new Session document in Firestore."""
    client = get_firestore_client()
    session = Session(
        student_id=payload.student_id,
        topic=payload.topic,
    )
    doc_ref = client.collection(COLLECTION_NAME).document(session.session_id)
    await doc_ref.set(session.to_firestore_dict())
    logger.info("Session created: %s", session.session_id)
    return session


async def get_session(session_id: str) -> Session | None:
    """Fetch a Session document by ID. Returns None if not found."""
    client = get_firestore_client()
    doc_ref = client.collection(COLLECTION_NAME).document(session_id)
    snapshot = await doc_ref.get()
    if not snapshot.exists:
        logger.debug("Session not found: %s", session_id)
        return None
    raw: dict[str, object] = snapshot.to_dict() or {}
    return Session.from_firestore_dict(raw)


async def append_turn(session_id: str, turn: ConversationTurn) -> Session:
    """
    Atomically append a ConversationTurn to the session's turns array.
    Also bumps updated_at. Returns the updated Session.
    """
    client = get_firestore_client()
    doc_ref = client.collection(COLLECTION_NAME).document(session_id)

    await doc_ref.update(
        {
            "turns": firestore.ArrayUnion([turn.to_firestore_dict()]),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    logger.debug("Turn appended to session %s (role=%s)", session_id, turn.role)

    updated = await get_session(session_id)
    if updated is None:
        raise ValueError(f"Session {session_id!r} not found after append_turn write")
    return updated


async def update_snapshot_url(session_id: str, snapshot: CanvasSnapshot) -> Session:
    """Update the latest_snapshot field on a session document. Returns the updated Session."""
    client = get_firestore_client()
    doc_ref = client.collection(COLLECTION_NAME).document(session_id)

    await doc_ref.update(
        {
            "latest_snapshot": snapshot.to_firestore_dict(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    logger.debug("Snapshot URL updated for session %s (gcs_path=%s)", session_id, snapshot.gcs_path)

    updated = await get_session(session_id)
    if updated is None:
        raise ValueError(f"Session {session_id!r} not found after update_snapshot_url write")
    return updated


async def delete_session(session_id: str) -> bool:
    """Delete a session document. Returns True if deleted, False if not found."""
    client = get_firestore_client()
    doc_ref = client.collection(COLLECTION_NAME).document(session_id)
    snapshot_check = await doc_ref.get()
    if not snapshot_check.exists:
        return False
    await doc_ref.delete()
    logger.info("Session deleted: %s", session_id)
    return True
