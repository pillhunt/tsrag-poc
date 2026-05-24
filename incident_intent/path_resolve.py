"""
Преобразование путей Windows (хост) → пути внутри Docker-контейнера.
"""

from __future__ import annotations

import os
from pathlib import Path


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
    rules: list[tuple[str, str]] = []
    rag_host = os.getenv("POC_RAG_HOST_PREFIX", "D:/RAG")
    rag_mount = os.getenv("POC_RAG_MOUNT", "/rag")
    rules.append((rag_host, rag_mount.rstrip("/")))

    caseone_host = os.getenv(
        "POC_CASEONE_HOST_PREFIX",
        "D:/RAG/tsrag/temp/uploads/caseone",
    )
    caseone_mount = os.getenv("POC_CASEONE_MOUNT", "/caseone")
    rules.append((caseone_host, caseone_mount.rstrip("/")))

    extra = os.getenv("POC_PATH_MAP", "")
    for part in extra.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        host, mount = part.split("=", 1)
        rules.append((host.strip(), mount.strip().rstrip("/")))

    return rules


def is_docker_runtime() -> bool:
    if os.getenv("POC_IN_DOCKER", "").lower() in ("1", "true", "yes"):
        return True
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
    rag_mount = os.getenv("POC_RAG_MOUNT", "/rag")

    if is_docker_runtime():
        hints.append(
            "Docker: укажите путь как D:\\RAG\\… (преобразуется в /rag/…) "
            f"или сразу {rag_mount}/<папка>."
        )

    ren_dirs = list_mount_entries(rag_mount, prefix="REN")
    if ren_dirs:
        hints.append(f"В {rag_mount} доступны: " + ", ".join(ren_dirs))
    elif Path(rag_mount).is_dir():
        hints.append(f"В {rag_mount} нет папок REN-* — проверьте POC_LOGS_HOST_DIR.")
    else:
        hints.append(
            f"Том {rag_mount} не смонтирован. "
            "Задайте POC_LOGS_HOST_DIR=D:/RAG в docker-compose и перезапустите."
        )

    if "ren-mskcaspro01" in _norm_key(logs_path) and ren_dirs:
        exact = [n for n in ren_dirs if n.upper() == "REN-MSKCASPRO01"]
        dated = [n for n in ren_dirs if n.upper().startswith("REN-MSKCASPRO01_")]
        if exact:
            hints.append(f"Найдена папка: {rag_mount}/{exact[0]}")
        elif dated:
            hints.append(f"Возможно, нужна папка с датой: {rag_mount}/{dated[0]}")

    caseone_mount = os.getenv("POC_CASEONE_MOUNT", "/caseone")
    if not Path(caseone_mount).exists():
        hints.append(
            f"Caseone ({caseone_mount}): смонтируйте POC_CASEONE_HOST_DIR "
            "или оставьте поле пустым."
        )

    return hints
