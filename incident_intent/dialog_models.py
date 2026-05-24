from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from incident_intent.models import IntentTableResponse


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class DialogState(BaseModel):
    incident_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    logs_path: str
    caseone_path: str
    intent_status: Literal["complete", "needs_clarification"] = "needs_clarification"
    intent: IntentTableResponse | None = None
    has_logs: bool = False
    awaiting_reply: bool = False
    user_forced_complete: bool = False
    upload_errors: list[str] = Field(default_factory=list)


class DialogResponse(BaseModel):
    incident_id: str
    dialog: DialogState
    system_notice: str | None = None
