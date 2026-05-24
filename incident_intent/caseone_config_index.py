"""
E3: индекс json/conf из caseone_path для досье шага 6 (без секретов).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from xml.etree import ElementTree

from incident_intent.e_analysis_models import (
    CaseoneConfigIndexRequest,
    CaseoneConfigIndexResponse,
    CaseoneConfigSnippet,
)

_CONFIG_GLOBS = (
    "appsettings*.json",
    "web.config",
    "*.config",
    "*.json",
    "*.yaml",
    "*.yml",
)
_SKIP_DIR_NAMES = frozenset(
    {
        "bin",
        "obj",
        "node_modules",
        ".git",
        "packages",
        "dist",
        "build",
    }
)
_SECRET_KEY_PARTS = (
    "password",
    "secret",
    "connectionstring",
    "connection string",
    "apikey",
    "api_key",
    "token",
    "credential",
    "privatekey",
    "pwd",
)
_MAX_FILE_BYTES = int(os.getenv("POC_CASEONE_MAX_FILE_BYTES", "524288"))
_MAX_FILES = int(os.getenv("POC_CASEONE_MAX_CONFIG_FILES", "80"))
_MAX_VALUE_LEN = 200


def _should_skip_dir(name: str) -> bool:
    return name.lower() in _SKIP_DIR_NAMES


def _is_config_file(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith((".json", ".config", ".yaml", ".yml")):
        return True
    if name.startswith("appsettings") and name.endswith(".json"):
        return True
    return name == "web.config"


def _mask_if_secret(key_path: str, value: str) -> str:
    low = key_path.lower()
    if any(part in low for part in _SECRET_KEY_PARTS):
        return "***"
    if len(value) > _MAX_VALUE_LEN:
        return value[:_MAX_VALUE_LEN] + "…"
    return value


def _flatten_json(
    obj: object,
    prefix: str,
    out: list[tuple[str, str]],
) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten_json(val, path, out)
    elif isinstance(obj, list):
        for i, val in enumerate(obj[:20]):
            _flatten_json(val, f"{prefix}[{i}]", out)
    else:
        text = str(obj).strip()
        if text:
            out.append((prefix, text))


def _parse_json_file(path: Path) -> list[tuple[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    pairs: list[tuple[str, str]] = []
    _flatten_json(data, "", pairs)
    return pairs


def _parse_xml_file(path: Path) -> list[tuple[str, str]]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    pairs: list[tuple[str, str]] = []

    def walk(elem: ElementTree.Element, prefix: str) -> None:
        tag = re.sub(r"\{.*\}", "", elem.tag)
        key = f"{prefix}/{tag}" if prefix else tag
        if elem.text and elem.text.strip() and not list(elem):
            pairs.append((key, elem.text.strip()))
        for child in elem:
            walk(child, key)

    walk(root, "")
    return pairs


def _score_entry(key_path: str, value: str, keywords: list[str]) -> int:
    if not keywords:
        return 1
    hay = f"{key_path} {value}".lower()
    return sum(1 for kw in keywords if kw and kw.lower() in hay)


def _discover_config_files(root: Path) -> list[Path]:
    found: list[Path] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        rel_depth = len(Path(dirpath).relative_to(root).parts)
        if rel_depth > 8:
            dirnames.clear()
            continue
        for name in filenames:
            path = Path(dirpath) / name
            if not _is_config_file(path):
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)
            if len(found) >= _MAX_FILES:
                return found
    return found


def index_caseone_config(req: CaseoneConfigIndexRequest) -> CaseoneConfigIndexResponse:
    root = Path(req.caseone_path.strip())
    if not root.is_dir():
        return CaseoneConfigIndexResponse(
            status="error",
            ran=False,
            caseone_path=str(root),
            errors=[f"Каталог caseone не найден: {root}"],
        )

    keywords = [k.strip() for k in req.search_keywords if k and k.strip()]
    files = _discover_config_files(root)
    if not files:
        return CaseoneConfigIndexResponse(
            status="ok",
            ran=False,
            caseone_path=str(root),
            files_scanned=0,
            conclusions=[
                f"В {root} не найдено конфигурационных json/config (лимит {_MAX_FILES} файлов).",
            ],
        )

    scored: list[CaseoneConfigSnippet] = []
    for path in files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        suffix = path.suffix.lower()
        if suffix == ".json":
            pairs = _parse_json_file(path)
        elif suffix in (".config", ".xml") or path.name.lower() == "web.config":
            pairs = _parse_xml_file(path)
        elif suffix in (".yaml", ".yml"):
            continue
        else:
            pairs = _parse_json_file(path)

        for key_path, value in pairs:
            if not key_path:
                continue
            masked = _mask_if_secret(key_path, value)
            score = _score_entry(key_path, value, keywords)
            if keywords and score == 0:
                continue
            scored.append(
                CaseoneConfigSnippet(
                    file=rel,
                    key_path=key_path,
                    value=masked,
                    score=score,
                )
            )

    scored.sort(key=lambda s: (-s.score, s.file, s.key_path))
    top = scored[: req.max_snippets]

    if not top and keywords:
        conclusions = [
            f"Просканировано {len(files)} конфигов в caseone; совпадений с keywords не найдено.",
        ]
    elif not top:
        conclusions = [
            f"Просканировано {len(files)} конфигов; укажите search_keywords на шаге 0 для ранжирования.",
        ]
    else:
        conclusions = [
            f"Из caseone отобрано {len(top)} фрагментов конфигурации (без секретов).",
            "Настройки — контекст, не доказательство причины инцидента.",
        ]

    return CaseoneConfigIndexResponse(
        status="ok",
        ran=True,
        caseone_path=str(root),
        files_scanned=len(files),
        snippets=top,
        conclusions=conclusions,
    )
