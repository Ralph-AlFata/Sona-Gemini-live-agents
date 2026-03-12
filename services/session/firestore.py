"""
Firestore async client and session CRUD operations.

Collection layout:
    sessions/{session_id}                → Session summary document
    sessions/{session_id}/turns/{turn_id} → ConversationTurn documents

The module holds a single AsyncClient instance initialised during app lifespan.
Access it via get_firestore_client().
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.async_client import AsyncClient  # type: ignore[import-untyped]

from gcp_auth import load_auth_config
from models import CanvasSnapshot, ConversationTurn, Session, SessionCreate

logger = logging.getLogger(__name__)

_firestore_client: AsyncClient | None = None

COLLECTION_NAME = "sessions"
TURN_SUBCOLLECTION = "turns"


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


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _session_doc_ref(client: AsyncClient, session_id: str):
    return client.collection(COLLECTION_NAME).document(session_id)


def _turns_col_ref(client: AsyncClient, session_id: str):
    return _session_doc_ref(client, session_id).collection(TURN_SUBCOLLECTION)


async def _load_turn_documents(session_id: str) -> list[dict[str, object]]:
    """Load all turn documents for a session, sorted by timestamp."""
    client = get_firestore_client()
    turns_raw: list[dict[str, object]] = []
    async for doc in _turns_col_ref(client, session_id).stream():
        raw = doc.to_dict()
        if isinstance(raw, dict):
            turns_raw.append(raw)
    turns_raw.sort(key=lambda item: str(item.get("timestamp", "")))
    return turns_raw


def _build_session_from_summary(
    *,
    session_id: str,
    summary_raw: dict[str, object],
    turns_raw: list[dict[str, object]],
) -> Session:
    """Construct API Session model from summary doc + turns subcollection."""
    raw_for_model = dict(summary_raw)
    raw_for_model["session_id"] = session_id
    raw_for_model["turns"] = turns_raw
    raw_turn_count = summary_raw.get("turn_count")
    if isinstance(raw_turn_count, int):
        raw_for_model["turn_count"] = max(raw_turn_count, len(turns_raw))
    else:
        raw_for_model["turn_count"] = len(turns_raw)
    if "last_turn_at" not in raw_for_model and turns_raw:
        raw_for_model["last_turn_at"] = turns_raw[-1].get("timestamp")
    return Session.from_firestore_dict(raw_for_model)


async def _delete_turn_documents(session_id: str) -> int:
    """Delete all turn subcollection docs in batches of 500."""
    client = get_firestore_client()
    col_ref = _turns_col_ref(client, session_id)
    batch = client.batch()
    deleted_count = 0
    async for doc in col_ref.stream():
        batch.delete(doc.reference)
        deleted_count += 1
        if deleted_count % 500 == 0:
            await batch.commit()
            batch = client.batch()
    if deleted_count % 500 != 0:
        await batch.commit()
    return deleted_count


# ─── CRUD operations ──────────────────────────────────────────────────────────

async def create_session(payload: SessionCreate) -> Session:
    """Create a new session summary document in Firestore."""
    client = get_firestore_client()
    session_id = payload.session_id or uuid4().hex
    doc_ref = _session_doc_ref(client, session_id)
    existing = await doc_ref.get()
    if existing.exists:
        logger.info("Session already exists: %s", session_id)
        existing_session = await get_session(session_id)
        if existing_session is None:
            raise ValueError(f"Session {session_id!r} exists but could not be loaded")
        return existing_session

    session = Session(
        session_id=session_id,
        student_id=payload.student_id,
        topic=payload.topic,
        turn_count=0,
        last_turn_at=None,
    )
    await doc_ref.set(session.to_firestore_summary_dict())
    logger.info("Session created: %s", session.session_id)
    return session


async def get_session(session_id: str) -> Session | None:
    """Fetch a session summary + turns by ID. Returns None if not found."""
    client = get_firestore_client()
    doc_ref = _session_doc_ref(client, session_id)
    snapshot = await doc_ref.get()
    if not snapshot.exists:
        logger.debug("Session not found: %s", session_id)
        return None
    summary_raw: dict[str, object] = snapshot.to_dict() or {}
    turns_raw = await _load_turn_documents(session_id)

    return _build_session_from_summary(
        session_id=session_id,
        summary_raw=summary_raw,
        turns_raw=turns_raw,
    )


async def append_turn(session_id: str, turn: ConversationTurn) -> Session:
    """
    Persist a ConversationTurn in turns subcollection.
    Also bumps summary updated_at / turn_count / last_turn_at.
    """
    client = get_firestore_client()
    session_ref = _session_doc_ref(client, session_id)
    turn_ref = _turns_col_ref(client, session_id).document(turn.turn_id)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    turn_ts_iso = turn.timestamp.isoformat()

    batch = client.batch()
    batch.set(turn_ref, turn.to_firestore_dict())
    batch.update(
        session_ref,
        {
            "updated_at": now_iso,
            "turn_count": firestore.Increment(1),
            "last_turn_at": turn_ts_iso,
        },
    )
    await batch.commit()

    logger.debug("Turn appended to session %s (role=%s)", session_id, turn.role)

    updated = await get_session(session_id)
    if updated is None:
        raise ValueError(f"Session {session_id!r} not found after append_turn write")
    return updated


async def update_snapshot_url(session_id: str, snapshot: CanvasSnapshot) -> Session:
    """Update the latest_snapshot field on a session document. Returns the updated Session."""
    client = get_firestore_client()
    doc_ref = _session_doc_ref(client, session_id)

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
    doc_ref = _session_doc_ref(client, session_id)
    snapshot_check = await doc_ref.get()
    if not snapshot_check.exists:
        return False
    deleted_turns = await _delete_turn_documents(session_id)
    await doc_ref.delete()
    logger.info("Session deleted: %s (turn_docs=%d)", session_id, deleted_turns)
    return True
