"""Загрузка файлов и распаковка zip в каталог инцидента."""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ZIP_BYTES = int(os.getenv("POC_ZIP_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_FILE_COUNT = int(os.getenv("POC_UPLOAD_MAX_FILE_COUNT", "1000"))
MAX_ZIP_PATH_DEPTH = 20
MAX_ZIP_PATH_LEN = 240


@dataclass
class UploadResult:
    saved_files: list[str]
    extracted_from_archive: list[str]
    errors: list[str]


def _safe_zip_target(dest_dir: Path, name: str) -> Path | None:
    clean = name.replace("\\", "/").lstrip("/")
    if not clean or clean.endswith("/"):
        return None
    parts = PurePosixPath(clean).parts
    if ".." in parts or len(parts) > MAX_ZIP_PATH_DEPTH:
        return None
    if len(clean) > MAX_ZIP_PATH_LEN:
        return None
    target = dest_dir.joinpath(*parts)
    try:
        target.resolve().relative_to(dest_dir.resolve())
    except ValueError:
        return None
    return target


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{999}{suffix}")


def _save_bytes(dest_dir: Path, filename: str, data: bytes) -> str:
    safe_name = Path(filename).name or "upload.bin"
    target = _unique_path(dest_dir / safe_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target.relative_to(dest_dir).as_posix()


def _expand_zip(dest_dir: Path, data: bytes, archive_name: str) -> tuple[list[str], list[str]]:
    saved: list[str] = []
    errors: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > MAX_FILE_COUNT:
                errors.append(f"В архиве {archive_name} больше {MAX_FILE_COUNT} файлов.")
                return saved, errors
            for info in members:
                total += info.file_size
                if total > MAX_ZIP_BYTES:
                    errors.append(
                        f"Распаковка {archive_name} прервана: превышен лимит {MAX_ZIP_BYTES} байт."
                    )
                    return saved, errors
                target = _safe_zip_target(dest_dir, info.filename)
                if target is None:
                    errors.append(f"Пропущен небезопасный путь в архиве: {info.filename}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
                saved.append(target.relative_to(dest_dir).as_posix())
    except zipfile.BadZipFile:
        errors.append(f"Файл {archive_name} не является корректным zip-архивом.")
    return saved, errors


def save_uploads(
    dest_dir: Path,
    files: list[tuple[str, bytes]],
) -> UploadResult:
    saved: list[str] = []
    extracted: list[str] = []
    errors: list[str] = []
    if len(files) > MAX_FILE_COUNT:
        return UploadResult([], [], [f"Слишком много файлов за раз (лимит {MAX_FILE_COUNT})."])

    total_bytes = sum(len(b) for _, b in files)
    if total_bytes > MAX_ZIP_BYTES:
        return UploadResult([], [], [f"Суммарный размер загрузки превышает {MAX_ZIP_BYTES} байт."])

    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for filename, data in files:
        if not data:
            continue
        count += 1
        lower = filename.lower()
        is_zip = lower.endswith(".zip")
        if is_zip:
            ex, err = _expand_zip(dest_dir, data, filename)
            extracted.extend(ex)
            saved.extend(ex)
            errors.extend(err)
        else:
            rel = _save_bytes(dest_dir, filename, data)
            saved.append(rel)
        if count > MAX_FILE_COUNT:
            errors.append(f"Превышен лимит {MAX_FILE_COUNT} файлов.")
            break

    return UploadResult(saved_files=saved, extracted_from_archive=extracted, errors=errors)
