import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


@contextmanager
def exclusive_command_lock(name: str) -> Iterator[bool]:
    lock_dir = Path(settings.LOG_DIR)
    lock_dir.mkdir(exist_ok=True)
    with open(lock_dir / f"{name}.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("%s is already running; skipping.", name)
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
