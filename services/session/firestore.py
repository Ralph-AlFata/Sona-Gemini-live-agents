"""
Firestore async client and session CRUD operations.

Collection layout:
    sessions/{session_id}                → Session summary document
    sessions/{session_id}/turns/{turn_id} → ConversationTurn documents
    sessions/{session_id}/elements/{element_id} → Materialized per-element docs

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
ELEMENTS_SUBCOLLECTION = "elements"


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


def _elements_col_ref(client: AsyncClient, session_id: str):
    return _session_doc_ref(client, session_id).collection(ELEMENTS_SUBCOLLECTION)


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


def _extract_dsl_messages_from_metadata(
    metadata: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Collect DSL messages from known metadata containers."""
    if not isinstance(metadata, dict):
        return []

    dsl_messages: list[dict[str, object]] = []
    top_level = metadata.get("dsl_messages")
    if isinstance(top_level, list):
        dsl_messages.extend(item for item in top_level if isinstance(item, dict))

    draw_results = metadata.get("draw_command_results")
    if isinstance(draw_results, list):
        for result in draw_results:
            if not isinstance(result, dict):
                continue
            nested = result.get("dsl_messages")
            if isinstance(nested, list):
                dsl_messages.extend(item for item in nested if isinstance(item, dict))

    return dsl_messages


def _coerce_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _compute_bbox_from_payload(payload: dict[str, object]) -> dict[str, float] | None:
    """Derive a normalized bbox from common DSL payload shapes."""
    points_raw = payload.get("points")
    if isinstance(points_raw, list):
        xs: list[float] = []
        ys: list[float] = []
        for point in points_raw:
            if not isinstance(point, dict):
                continue
            x = _coerce_float(point.get("x"))
            y = _coerce_float(point.get("y"))
            if x is None or y is None:
                continue
            xs.append(x)
            ys.append(y)
        if xs and ys:
            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
            return {
                "x": min_x,
                "y": min_y,
                "width": max(max_x - min_x, 0.0),
                "height": max(max_y - min_y, 0.0),
            }

    x = _coerce_float(payload.get("x"))
    y = _coerce_float(payload.get("y"))
    if x is None or y is None:
        return None

    width = _coerce_float(payload.get("width"))
    height = _coerce_float(payload.get("height"))
    return {
        "x": x,
        "y": y,
        "width": max(width if width is not None else 0.0, 0.0),
        "height": max(height if height is not None else 0.0, 0.0),
    }


def _apply_style_update_to_payload(
    payload: dict[str, object],
    style_update: dict[str, object],
) -> dict[str, object]:
    """
    Apply style updates across both known payload style layouts:
    - flattened frontend fields (`color`, `stroke_width`, ...)
    - nested internal `style` object (`stroke_color`, `stroke_width`, ...)
    """
    updated_payload = dict(payload)

    for key, value in style_update.items():
        updated_payload[key] = value

    nested_style_raw = updated_payload.get("style")
    nested_style = dict(nested_style_raw) if isinstance(nested_style_raw, dict) else {}
    key_map = {
        "color": "stroke_color",
        "stroke_width": "stroke_width",
        "fill_color": "fill_color",
        "opacity": "opacity",
        "z_index": "z_index",
        "delay_ms": "delay_ms",
        "animate": "animate",
    }
    for key, value in style_update.items():
        nested_style[key_map.get(key, key)] = value
    if nested_style:
        updated_payload["style"] = nested_style

    return updated_payload


def _build_element_entry(
    *,
    element_id: str,
    element_type: str | None,
    payload: dict[str, object],
    message: dict[str, object],
) -> dict[str, object]:
    """Construct stored element snapshot for the materialized session index."""
    entry: dict[str, object] = {
        "element_id": element_id,
        "element_type": element_type or "unknown",
        "payload": payload,
    }
    bbox = _compute_bbox_from_payload(payload)
    if bbox is not None:
        entry["bbox"] = bbox
    message_id = message.get("id")
    if isinstance(message_id, str):
        entry["last_message_id"] = message_id
    message_type = message.get("type")
    if isinstance(message_type, str):
        entry["last_message_type"] = message_type
    timestamp = message.get("timestamp")
    entry["updated_at"] = (
        timestamp
        if isinstance(timestamp, str)
        else datetime.now(tz=timezone.utc).isoformat()
    )
    return entry


def _apply_dsl_messages_to_elements(
    *,
    elements_by_id: dict[str, dict[str, object]],
    dsl_messages: list[dict[str, object]],
) -> bool:
    """
    Reconcile session element index from ordered DSL messages.

    Returns True when in-memory state changed.
    """
    changed = False

    for message in dsl_messages:
        message_type = message.get("type")
        payload_raw = message.get("payload")
        if not isinstance(message_type, str) or not isinstance(payload_raw, dict):
            continue

        if message_type == "element_created":
            element_id = payload_raw.get("element_id")
            if not isinstance(element_id, str) or not element_id:
                continue
            element_type = payload_raw.get("element_type")
            element_payload_raw = payload_raw.get("payload")
            element_payload = (
                dict(element_payload_raw) if isinstance(element_payload_raw, dict) else {}
            )
            next_entry = _build_element_entry(
                element_id=element_id,
                element_type=element_type if isinstance(element_type, str) else None,
                payload=element_payload,
                message=message,
            )
            if elements_by_id.get(element_id) != next_entry:
                elements_by_id[element_id] = next_entry
                changed = True
            continue

        if message_type == "elements_transformed":
            transformed_raw = payload_raw.get("elements")
            if not isinstance(transformed_raw, list):
                continue
            for transformed in transformed_raw:
                if not isinstance(transformed, dict):
                    continue
                element_id = transformed.get("element_id")
                if not isinstance(element_id, str) or not element_id:
                    continue
                payload_value = transformed.get("payload")
                element_payload = dict(payload_value) if isinstance(payload_value, dict) else {}
                element_type_raw = transformed.get("element_type")
                element_type = element_type_raw if isinstance(element_type_raw, str) else None
                if element_type is None:
                    existing = elements_by_id.get(element_id)
                    existing_type = existing.get("element_type") if isinstance(existing, dict) else None
                    if isinstance(existing_type, str):
                        element_type = existing_type
                next_entry = _build_element_entry(
                    element_id=element_id,
                    element_type=element_type,
                    payload=element_payload,
                    message=message,
                )
                if elements_by_id.get(element_id) != next_entry:
                    elements_by_id[element_id] = next_entry
                    changed = True
            continue

        if message_type == "elements_restyled":
            restyled_raw = payload_raw.get("elements")
            if not isinstance(restyled_raw, list):
                continue
            for restyled in restyled_raw:
                if not isinstance(restyled, dict):
                    continue
                element_id = restyled.get("element_id")
                style_raw = restyled.get("style")
                existing = elements_by_id.get(element_id) if isinstance(element_id, str) else None
                if (
                    not isinstance(element_id, str)
                    or not element_id
                    or not isinstance(style_raw, dict)
                    or not isinstance(existing, dict)
                ):
                    continue
                existing_payload_raw = existing.get("payload")
                existing_payload = (
                    dict(existing_payload_raw) if isinstance(existing_payload_raw, dict) else {}
                )
                merged_payload = _apply_style_update_to_payload(existing_payload, style_raw)
                element_type_raw = restyled.get("element_type")
                element_type = (
                    element_type_raw if isinstance(element_type_raw, str) else existing.get("element_type")
                )
                next_entry = _build_element_entry(
                    element_id=element_id,
                    element_type=element_type if isinstance(element_type, str) else None,
                    payload=merged_payload,
                    message=message,
                )
                if elements_by_id.get(element_id) != next_entry:
                    elements_by_id[element_id] = next_entry
                    changed = True
            continue

        if message_type == "elements_deleted":
            deleted_ids = payload_raw.get("element_ids")
            if not isinstance(deleted_ids, list):
                continue
            for raw_element_id in deleted_ids:
                if isinstance(raw_element_id, str) and raw_element_id in elements_by_id:
                    elements_by_id.pop(raw_element_id, None)
                    changed = True
            continue

        if message_type == "clear":
            if elements_by_id:
                elements_by_id.clear()
                changed = True

    return changed


async def _load_elements_index(session_id: str) -> dict[str, dict[str, object]]:
    """Load element documents for a session keyed by element_id."""
    client = get_firestore_client()
    parsed: dict[str, dict[str, object]] = {}
    async for doc in _elements_col_ref(client, session_id).stream():
        raw = doc.to_dict()
        if not isinstance(raw, dict):
            continue
        element_id_raw = raw.get("element_id")
        if isinstance(element_id_raw, str) and element_id_raw:
            parsed[element_id_raw] = dict(raw)
            continue
        parsed[doc.id] = dict(raw)
    return parsed


async def _write_elements_index(
    *,
    session_id: str,
    elements_by_id: dict[str, dict[str, object]],
    previous_element_ids: set[str],
) -> None:
    """Persist element documents and delete any removed IDs."""
    client = get_firestore_client()
    col_ref = _elements_col_ref(client, session_id)
    next_element_ids = set(elements_by_id.keys())
    removed_element_ids = previous_element_ids - next_element_ids

    batch = client.batch()
    operation_count = 0

    for element_id, entry in elements_by_id.items():
        entry_to_write = dict(entry)
        entry_to_write["element_id"] = element_id
        entry_to_write["session_id"] = session_id
        batch.set(col_ref.document(element_id), entry_to_write)
        operation_count += 1
        if operation_count >= 500:
            await batch.commit()
            batch = client.batch()
            operation_count = 0

    for element_id in removed_element_ids:
        batch.delete(col_ref.document(element_id))
        operation_count += 1
        if operation_count >= 500:
            await batch.commit()
            batch = client.batch()
            operation_count = 0

    if operation_count > 0:
        await batch.commit()


async def _reconcile_elements_from_turn(
    *,
    session_id: str,
    turn: ConversationTurn,
) -> None:
    """Update session element collection from DSL messages carried by a turn."""
    dsl_messages = _extract_dsl_messages_from_metadata(turn.metadata)
    if not dsl_messages:
        return
    elements_by_id = await _load_elements_index(session_id)
    previous_element_ids = set(elements_by_id.keys())
    changed = _apply_dsl_messages_to_elements(
        elements_by_id=elements_by_id,
        dsl_messages=dsl_messages,
    )
    if not changed:
        return
    await _write_elements_index(
        session_id=session_id,
        elements_by_id=elements_by_id,
        previous_element_ids=previous_element_ids,
    )


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
    return await _delete_subcollection_documents(
        session_id=session_id,
        subcollection_name=TURN_SUBCOLLECTION,
    )


async def _delete_subcollection_documents(
    *,
    session_id: str,
    subcollection_name: str,
) -> int:
    """Delete all docs in a session subcollection in batches of 500."""
    client = get_firestore_client()
    col_ref = _session_doc_ref(client, session_id).collection(subcollection_name)
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
    student_id = payload.student_id or f"student_{uuid4().hex[:8]}"
    doc_ref = _session_doc_ref(client, session_id)
    existing = await doc_ref.get()
    if existing.exists:
        logger.info("Session already exists: %s", session_id)
        existing_session = await get_session(session_id)
        if existing_session is None:
            raise ValueError(f"Session {session_id!r} exists but could not be loaded")
        if existing_session.student_id != student_id:
            raise PermissionError(
                f"Session {session_id!r} is owned by a different student_id"
            )
        return existing_session

    session = Session(
        session_id=session_id,
        student_id=student_id,
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

    try:
        await _reconcile_elements_from_turn(session_id=session_id, turn=turn)
    except Exception:
        logger.exception(
            "Element index reconciliation failed for session %s turn %s",
            session_id,
            turn.turn_id,
        )

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
    deleted_element_docs = await _delete_subcollection_documents(
        session_id=session_id,
        subcollection_name=ELEMENTS_SUBCOLLECTION,
    )
    await doc_ref.delete()
    logger.info(
        "Session deleted: %s (turn_docs=%d, element_docs=%d)",
        session_id,
        deleted_turns,
        deleted_element_docs,
    )
    return True
