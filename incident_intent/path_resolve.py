"""
Преобразование путей и подсказки для смонтированных каталогов (логи, caseone).
"""

from __future__ import annotations

import os
from pathlib import Path

from incident_intent.poc_paths import CASEONE_CONTAINER_PATH, logs_dir


def _norm_key(path: str) -> str:
    p = path.strip().replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0].upper() + p[1:]
    return p.rstrip("/").lower()


def _suffix_after_host(original: str, host_prefix: str) -> str | None:
    """Суффикс пути после host_prefix; регистр суффикса как во вводе."""
    orig = original.strip().replace("\\", "/")
    host = host_prefix.strip().replace("\\", "/").rstrip("/")
    if _norm_key(orig) == _norm_key(host):
        return ""
    needle = host.lower() + "/"
    if not orig.lower().startswith(needle):
        return None
    return orig[len(host) + 1 :]


def _mapping_rules() -> list[tuple[str, str]]:
    """Доп. правила из POC_PATH_MAP=host=mount;host2=mount2."""
    rules: list[tuple[str, str]] = []
    extra = os.getenv("POC_PATH_MAP", "")
    for part in extra.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        host, mount = part.split("=", 1)
        rules.append((host.strip(), mount.strip().rstrip("/")))
    return rules


def is_docker_runtime() -> bool:
    return Path("/.dockerenv").exists()


def resolve_host_path(path: str | None) -> tuple[str | None, str | None]:
    if not path or not path.strip():
        return None, None

    original = path.strip()
    try:
        candidate = Path(original)
        if candidate.exists():
            return str(candidate.resolve()), None
    except OSError:
        pass

    for host_prefix, mount in _mapping_rules():
        suffix = _suffix_after_host(original, host_prefix)
        if suffix is None:
            continue
        mapped = mount if suffix == "" else f"{mount}/{suffix}"
        if Path(mapped).exists():
            note = f"Путь для контейнера: {original} → {mapped}"
            return mapped, note

    return original, None


def list_mount_entries(mount: str, *, prefix: str = "", limit: int = 15) -> list[str]:
    root = Path(mount)
    if not root.is_dir():
        return []
    names: list[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if prefix and not entry.name.upper().startswith(prefix.upper()):
                continue
            names.append(entry.name)
            if len(names) >= limit:
                break
    except OSError:
        return []
    return names


def path_hints_for_missing(logs_path: str) -> list[str]:
    hints: list[str] = []
    logs_mount = str(logs_dir())

    if is_docker_runtime():
        hints.append(
            f"Docker: положите папки REN-* в ./logs на хосте "
            f"и укажите путь {logs_mount}/<папка> (или загрузите логи в инцидент)."
        )

    ren_dirs = list_mount_entries(logs_mount, prefix="REN")
    if ren_dirs:
        hints.append(f"В {logs_mount} доступны: " + ", ".join(ren_dirs))
    elif Path(logs_mount).is_dir():
        hints.append(
            f"В {logs_mount} нет папок REN-* — добавьте их в каталог logs/ проекта."
        )
    else:
        hints.append(
            f"Каталог логов {logs_mount} недоступен — проверьте том ./logs в docker-compose."
        )

    if "ren-mskcaspro01" in _norm_key(logs_path) and ren_dirs:
        exact = [n for n in ren_dirs if n.upper() == "REN-MSKCASPRO01"]
        dated = [n for n in ren_dirs if n.upper().startswith("REN-MSKCASPRO01_")]
        if exact:
            hints.append(f"Найдена папка: {logs_mount}/{exact[0]}")
        elif dated:
            hints.append(f"Возможно, нужна папка с датой: {logs_mount}/{dated[0]}")

    if not Path(CASEONE_CONTAINER_PATH).exists():
        hints.append(
            f"Caseone: задайте CASEONE_HOST_DIR в env/docker.env "
            f"(монтируется в {CASEONE_CONTAINER_PATH}) или оставьте поле пустым."
        )

    return hints
