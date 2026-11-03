"""프로세스끼리 같이 쓰는 잠금 (2026-11-03).

공개 서버는 프로세스 3개(ZIPGENIE_WORKERS)로 돈다. threading.Lock 은 프로세스 안에서만 통하므로 "확인 → 기록" 처럼
사이에 다른 프로세스가 끼면 안 되는 일(남용 제한·메일 상한)과, PC 전체에서 하나만 돌아야 하는 일(공유 카드용 브라우저)은
data/locks/<이름>.lock 파일 잠금으로 묶는다. Windows 는 msvcrt, 그 밖은 fcntl.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from .db import ROOT

_DIR = ROOT / "data" / "locks"
_local: dict[str, threading.Lock] = {}
_local_guard = threading.Lock()


def _thread_lock(name: str) -> threading.Lock:
    with _local_guard:
        return _local.setdefault(name, threading.Lock())


def _try_lock_file(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_file(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def xlock(name: str, timeout: float = 5.0, wait: bool = True):
    """잠금을 잡으면 True, 못 잡으면 False 를 내준다.
    wait=False 면 이미 누가 잡고 있을 때 바로 False (그 일을 건너뛸 때). wait=True 면 timeout 초까지 기다리고,
    그래도 못 잡으면 False — 잠금 때문에 서비스가 멈추지 않게 호출 쪽이 그냥 진행할지 정한다."""
    tl = _thread_lock(name)
    held = tl.acquire(timeout=timeout) if wait else tl.acquire(blocking=False)
    if not held:
        yield False
        return
    fd = None
    got = False
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_DIR / f"{name}.lock"), os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + (timeout if wait else 0)
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            if _try_lock_file(fd):
                got = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        yield got
    finally:
        if fd is not None:
            if got:
                _unlock_file(fd)
            os.close(fd)
        tl.release()
