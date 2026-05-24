from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LogFileInfo(BaseModel):
    relative_path: str
    size_bytes: int
    priority: bool = False


class SourcesCheck(BaseModel):
    logs_path: str
    logs_exists: bool
    logs_is_directory: bool
    logs_is_file: bool = False
    recursive_search: bool = True
    max_depth: int | None = None
    log_file_count: int = 0
    log_files: list[LogFileInfo] = Field(default_factory=list)
    caseone_path: str | None = None
    caseone_exists: bool | None = None
    caseone_is_directory: bool | None = None
    errors: list[str] = Field(default_factory=list)


class FileMatchStats(BaseModel):
    relative_path: str
    match_count: int
    priority: bool = False


class SampleLine(BaseModel):
    file: str
    line_number: int
    text: str


class TimeWindowLine(BaseModel):
    """Строка лога внутри временного окна (срез для шагов 3–4)."""

    file: str
    line_number: int
    text: str


class FilterLogsRequest(BaseModel):
    logs_path: str = Field(min_length=1)
    log_search_patterns: list[str] = Field(min_length=1)
    caseone_path: str | None = None
    recursive: bool = Field(
        default=True,
        description="Искать *.log во всех подкаталогах logs_path",
    )
    max_depth: int | None = Field(
        default=None,
        ge=0,
        description="Макс. глубина вложенности (0 = только корень); null = без ограничения",
    )
    max_sample_lines_per_file: int = Field(default=5, ge=0, le=50)
    max_total_sample_lines: int = Field(default=80, ge=0, le=500)
    max_time_window_lines: int = Field(
        default=100_000,
        ge=1,
        le=500_000,
        description="Макс. строк среза для передачи в шаги 3–4",
    )


class FilterLogsResponse(BaseModel):
    status: Literal["ok", "error"]
    step: Literal["sources", "filter", "sources_and_filter"]
    sources: SourcesCheck | None = None
    patterns_used: list[str] = Field(default_factory=list)
    total_matching_lines: int = 0
    by_file: list[FileMatchStats] = Field(default_factory=list)
    sample_lines: list[SampleLine] = Field(default_factory=list)
    time_window_lines: list[TimeWindowLine] = Field(default_factory=list)
    files_in_window: list[str] = Field(default_factory=list)
    time_window_truncated: bool = False
    time_window_total_count: int = 0
    errors: list[str] = Field(default_factory=list)
