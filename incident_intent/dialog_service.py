"""Диалог инцидента: старт, сообщения, загрузка файлов, шаг 0."""

from __future__ import annotations

import uuid
from pathlib import Path

from incident_intent.artifact_upload import save_uploads
from incident_intent.dialog_models import ChatMessage, DialogResponse, DialogState
from incident_intent.dialog_session import get_session, save_session
from incident_intent.extractor import build_intent_table
from incident_intent.models import IntentTableRequest
from incident_intent.poc_paths import caseone_dir, incident_dir, incident_has_log_files
from incident_intent.skip_utils import is_user_done_message


def _dialog_text(messages: list[ChatMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        if m.role == "user":
            lines.append(f"Пользователь: {m.content}")
        elif m.role == "assistant":
            lines.append(f"Ассистент: {m.content}")
    return "\n".join(lines)


def _assistant_reply(intent) -> str | None:
    if intent.clarifying_questions and intent.status == "needs_clarification":
        return intent.clarifying_questions[0]
    if intent.status == "complete" and intent.table:
        tw = intent.table
        parts = [
            "Достаточно данных для шагов 1–6.",
            f"Дата: {tw.incident_date.value or '—'}.",
            f"Окно: {tw.time_window_start.value or '—'} – {tw.time_window_end.value or '—'}.",
        ]
        if tw.time_filter_mode == "full_corpus":
            parts.append(
                "Внимание: временной интервал не задан — анализ по всем строкам логов (до лимита)."
            )
        return " ".join(parts)
    if intent.clarifying_questions:
        return intent.clarifying_questions[0]
    return None


def _should_append_assistant(messages: list[ChatMessage], reply: str) -> bool:
    """Не дублировать в чате тот же вопрос, если пользователь уже ответил после него."""
    rs = reply.strip()
    last_assistant_idx: int | None = None
    for i, m in enumerate(messages):
        if m.role == "assistant":
            last_assistant_idx = i
    if last_assistant_idx is None:
        return True
    if messages[last_assistant_idx].content.strip() != rs:
        return True
    for m in messages[last_assistant_idx + 1 :]:
        if m.role == "user" and m.content.strip():
            return False
    return True


def _should_rerun_step0(
    *,
    has_user_text: bool,
    user_force_complete: bool,
) -> bool:
    """LLM шаг 0 — только при тексте пользователя или явном «достаточно»; загрузка файлов не считается ходом диалога."""
    if has_user_text or user_force_complete:
        return True
    return False


def _on_upload_only(state: DialogState) -> None:
    """Обновить состояние после загрузки без вызова LLM и без новых реплик ассистента."""
    state.has_logs = incident_has_log_files(state.incident_id)


def _prompt_after_logs_only_start(state: DialogState) -> None:
    """Старт только с файлами: один раз попросить описание без LLM."""
    if state.intent is not None:
        return
    prompt = (
        "Логи получены. Опишите инцидент: что произошло, когда (дата и время или «примерно»)."
    )
    if any(m.role == "assistant" and m.content.strip() == prompt for m in state.messages):
        return
    state.messages.append(ChatMessage(role="assistant", content=prompt))
    state.awaiting_reply = True
    state.intent_status = "needs_clarification"


async def _run_step0(state: DialogState, *, user_force_complete: bool = False) -> None:
    req = IntentTableRequest(
        incident_description=_dialog_text(state.messages),
        logs_path=state.logs_path,
        caseone_path=state.caseone_path,
        user_force_complete=user_force_complete,
    )
    intent = await build_intent_table(req)
    state.intent = intent
    state.intent_status = intent.status
    state.user_forced_complete = user_force_complete
    state.awaiting_reply = intent.status == "needs_clarification"
    state.has_logs = incident_has_log_files(state.incident_id)

    reply = _assistant_reply(intent)
    if reply and _should_append_assistant(state.messages, reply):
        state.messages.append(ChatMessage(role="assistant", content=reply))


def _apply_uploads(state: DialogState, files: list[tuple[str, bytes]]) -> str | None:
    if not files:
        return None
    result = save_uploads(Path(state.logs_path), files)
    state.upload_errors.extend(result.errors)
    state.has_logs = incident_has_log_files(state.incident_id)
    if result.saved_files:
        n = len(result.saved_files)
        arch = len(result.extracted_from_archive)
        if arch:
            return f"Загружено и распаковано: {arch} файлов из архива(ов) (всего {n} файлов в инциденте)."
        return f"Загружено файлов: {n}."
    if result.errors:
        return result.errors[0]
    return "Файлы не сохранены."


def _new_state(incident_id: str | None = None) -> DialogState:
    iid = incident_id or str(uuid.uuid4())
    logs = str(incident_dir(iid))
    co = str(caseone_dir())
    return DialogState(
        incident_id=iid,
        logs_path=logs,
        caseone_path=co,
    )


async def start_dialog(
    message: str,
    files: list[tuple[str, bytes]] | None = None,
) -> DialogResponse:
    text = message.strip()
    if not text and not files:
        raise ValueError("Нужно сообщение или файлы.")

    state = _new_state()
    if text:
        state.messages.append(ChatMessage(role="user", content=text))

    notice = _apply_uploads(state, files or [])
    if notice:
        state.messages.append(ChatMessage(role="system", content=notice))

    has_text = bool(text)
    force = is_user_done_message(text) if has_text else False
    if _should_rerun_step0(has_user_text=has_text, user_force_complete=force):
        await _run_step0(state, user_force_complete=force)
    else:
        _on_upload_only(state)
        if not has_text and not state.intent:
            _prompt_after_logs_only_start(state)

    save_session(state)
    return DialogResponse(incident_id=state.incident_id, dialog=state, system_notice=notice)


async def continue_dialog(
    incident_id: str,
    message: str,
    files: list[tuple[str, bytes]] | None = None,
) -> DialogResponse:
    state = get_session(incident_id)
    if state is None:
        raise KeyError(f"Инцидент не найден: {incident_id}")

    text = message.strip()
    if not text and not files:
        raise ValueError("Нужно сообщение или файлы.")

    if text:
        state.messages.append(ChatMessage(role="user", content=text))

    notice = _apply_uploads(state, files or [])
    if notice:
        state.messages.append(ChatMessage(role="system", content=notice))

    has_text = bool(text)
    force = is_user_done_message(text) if has_text else False
    if _should_rerun_step0(has_user_text=has_text, user_force_complete=force):
        await _run_step0(state, user_force_complete=force)
    else:
        _on_upload_only(state)

    save_session(state)
    return DialogResponse(incident_id=state.incident_id, dialog=state, system_notice=notice)


async def upload_artifacts(
    incident_id: str,
    files: list[tuple[str, bytes]],
) -> DialogResponse:
    state = get_session(incident_id)
    if state is None:
        raise KeyError(f"Инцидент не найден: {incident_id}")

    notice = _apply_uploads(state, files)
    if notice:
        state.messages.append(ChatMessage(role="system", content=notice))

    _on_upload_only(state)
    save_session(state)
    return DialogResponse(incident_id=state.incident_id, dialog=state, system_notice=notice)


def get_dialog(incident_id: str) -> DialogState:
    state = get_session(incident_id)
    if state is None:
        raise KeyError(f"Инцидент не найден: {incident_id}")
    return state
