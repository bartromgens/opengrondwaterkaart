import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def command_lock_path(name: str) -> Path:
    return Path(settings.LOG_DIR) / f"{name}.lock"


@contextmanager
def exclusive_command_lock(name: str) -> Iterator[bool]:
    lock_dir = Path(settings.LOG_DIR)
    lock_dir.mkdir(exist_ok=True)
    lock_path = command_lock_path(name)
    lock_path.touch(exist_ok=True)
    with open(lock_path, "r+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = fh.read().strip() or "unknown process"
            logger.warning(
                "%s is already running; exclusive lock file %s is held by %s; skipping.",
                name,
                lock_path,
                holder,
            )
            yield False
            return
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()}")
        fh.flush()
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
