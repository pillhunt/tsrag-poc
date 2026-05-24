"""In-memory хранилище диалогов (без восстановления после перезагрузки страницы)."""

from __future__ import annotations

from incident_intent.dialog_models import DialogState

_sessions: dict[str, DialogState] = {}


def get_session(incident_id: str) -> DialogState | None:
    return _sessions.get(incident_id)


def save_session(state: DialogState) -> None:
    _sessions[state.incident_id] = state


def delete_session(incident_id: str) -> None:
    _sessions.pop(incident_id, None)
