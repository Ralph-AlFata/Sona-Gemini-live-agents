"""
Element store abstraction for the Drawing Command Service.

Defines the ElementStore protocol and an in-memory implementation used
during local development and testing. A Firestore-backed implementation
lives in firestore_store.py and is activated via config.use_firestore.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class BBox:
    """Axis-aligned bounding box in normalized [0, 1] canvas coordinates."""

    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
class StoredElement:
    """An element persisted in the element store for a session."""

    element_id: str
    element_type: str  # "shape" | "text" | "freehand" | "highlight"
    payload: dict      # Type-specific drawing data (serialisable to JSON)
    bbox: BBox         # Bounding box used for spatial queries (e.g. erase region)


@runtime_checkable
class ElementStore(Protocol):
    """
    Async protocol for reading and writing canvas elements by session.

    All implementations must support the four core operations below.
    Spatial queries (e.g. erase region) are handled by callers who
    read all elements and filter in memory.
    """

    async def get_all_elements(self, session_id: str) -> dict[str, StoredElement]:
        """Return a mutable snapshot of all elements for a session."""
        ...

    async def put_element(self, session_id: str, element: StoredElement) -> None:
        """Insert or overwrite a single element."""
        ...

    async def delete_element(self, session_id: str, element_id: str) -> None:
        """Remove a single element by ID. No-op if not found."""
        ...

    async def clear_session(self, session_id: str) -> None:
        """Delete all elements for a session."""
        ...


class InMemoryElementStore:
    """
    Thread-safe in-memory element store backed by a nested dict.

    Used for local development and testing. Data is lost on process restart.
    Activate Firestore persistence by setting USE_FIRESTORE=true in .env.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, StoredElement]] = {}

    async def get_all_elements(self, session_id: str) -> dict[str, StoredElement]:
        """Return the live session dict (mutations are reflected immediately)."""
        return self._store.setdefault(session_id, {})

    async def put_element(self, session_id: str, element: StoredElement) -> None:
        self._store.setdefault(session_id, {})[element.element_id] = element

    async def delete_element(self, session_id: str, element_id: str) -> None:
        self._store.get(session_id, {}).pop(element_id, None)

    async def clear_session(self, session_id: str) -> None:
        self._store[session_id] = {}
