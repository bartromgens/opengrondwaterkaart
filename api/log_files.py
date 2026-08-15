import re
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

LOG_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.log(?:\.\d+)?$")
DEFAULT_LOG_LINES = 2000
MAX_LOG_LINES = 10000


def parse_line_count(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_LOG_LINES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LOG_LINES
    return min(max(value, 1), MAX_LOG_LINES)


def resolve_log_file(name: str) -> Path | None:
    if not LOG_NAME_RE.fullmatch(name):
        return None
    log_dir = Path(settings.LOG_DIR).resolve()
    path = (log_dir / name).resolve()
    if not path.is_relative_to(log_dir) or not path.is_file():
        return None
    return path


def _file_payload(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def list_log_files() -> list[dict]:
    log_dir = Path(settings.LOG_DIR)
    if not log_dir.is_dir():
        return []
    files = [
        _file_payload(path)
        for path in log_dir.iterdir()
        if path.is_file() and LOG_NAME_RE.fullmatch(path.name)
    ]
    files.sort(key=lambda item: item["modified"], reverse=True)
    return files


def tail_lines(path: Path, max_lines: int) -> tuple[str, bool]:
    size = path.stat().st_size
    if size == 0:
        return "", False

    chunk = min(size, max(max_lines * 256, 8192))
    while True:
        with path.open("rb") as handle:
            handle.seek(size - chunk)
            data = handle.read()
        if size > chunk:
            newline = data.find(b"\n")
            if newline != -1:
                data = data[newline + 1 :]
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) >= max_lines or chunk >= size:
            truncated = chunk < size or len(lines) > max_lines
            return "\n".join(lines[-max_lines:]), truncated
        chunk = min(size, chunk * 2)


def read_log_file(path: Path, max_lines: int) -> dict:
    content, truncated = tail_lines(path, max_lines)
    payload = _file_payload(path)
    payload.update(
        {
            "lines": max_lines,
            "truncated": truncated,
            "content": content,
        }
    )
    return payload
