from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _override_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep tests deterministic regardless of developer .env values.
    """
    from config import settings

    monkeypatch.setattr(settings, "drawing_auth_enabled", False)
    monkeypatch.setattr(settings, "drawing_auth_audience", "")
    monkeypatch.setattr(settings, "use_firestore", False)
