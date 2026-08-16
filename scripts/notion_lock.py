#!/usr/bin/env python3
"""
Multi-process / multi-host lock for Notion sync/export.

Default: POSIX file lock (fcntl) — concurrent processes on one machine.
Optional: Redis when NOTION_LOCK_REDIS_URL is set — multi-host.

Usage:
    from notion_lock import notion_lock
    with notion_lock("sync"):
        run_sync()
"""
from __future__ import annotations

import atexit
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_DIR = Path(os.environ.get("NOTION_LOCK_DIR", "/tmp/stargate-notion-locks"))
LOCK_TIMEOUT = float(os.environ.get("NOTION_LOCK_TIMEOUT", "600"))
REDIS_URL = os.environ.get("NOTION_LOCK_REDIS_URL", "").strip()
REDIS_TTL = int(os.environ.get("NOTION_LOCK_REDIS_TTL", "900"))


class LockTimeoutError(TimeoutError):
    pass


class FileProcessLock:
    def __init__(self, name: str, timeout: float = LOCK_TIMEOUT):
        self.name = name
        self.timeout = timeout
        self._path = LOCK_DIR / f"{name}.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        import fcntl

        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        fd = os.open(str(self._path), os.O_RDWR)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(fd, 0)
                os.write(fd, f"pid={os.getpid()} ts={time.time():.0f}\n".encode())
                self._fd = fd
                atexit.register(self.release)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockTimeoutError(
                        f"Could not acquire file lock '{self.name}' within {self.timeout}s "
                        f"(another Notion sync/export may be running)"
                    )
                time.sleep(0.25)

    def release(self) -> None:
        import fcntl

        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None
        try:
            atexit.unregister(self.release)
        except Exception:
            pass

    def __enter__(self) -> "FileProcessLock":
        self.acquire()
        return self

    def __exit__(self, *args) -> None:
        self.release()


class RedisProcessLock:
    def __init__(self, name: str, timeout: float = LOCK_TIMEOUT, ttl: int = REDIS_TTL):
        self.name = name
        self.timeout = timeout
        self.ttl = ttl
        self._key = f"notion-lock:{name}"
        self._token = f"{os.getpid()}-{time.time()}"
        self._redis = None

    def _client(self):
        if self._redis is None:
            try:
                import redis
            except ImportError as e:
                raise RuntimeError(
                    "NOTION_LOCK_REDIS_URL set but redis package missing: pip install redis"
                ) from e
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    def acquire(self) -> None:
        r = self._client()
        deadline = time.monotonic() + self.timeout
        while True:
            if r.set(self._key, self._token, nx=True, ex=self.ttl):
                atexit.register(self.release)
                return
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"Could not acquire Redis lock '{self.name}' within {self.timeout}s"
                )
            time.sleep(0.25)

    def release(self) -> None:
        if self._redis is None:
            return
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        try:
            self._redis.eval(script, 1, self._key, self._token)
        except Exception:
            pass
        try:
            atexit.unregister(self.release)
        except Exception:
            pass

    def __enter__(self) -> "RedisProcessLock":
        self.acquire()
        return self

    def __exit__(self, *args) -> None:
        self.release()


def make_lock(name: str, timeout: float | None = None):
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    if REDIS_URL:
        return RedisProcessLock(name, timeout=timeout)
    return FileProcessLock(name, timeout=timeout)


@contextmanager
def notion_lock(name: str = "notion-api", timeout: float | None = None) -> Iterator[None]:
    lock = make_lock(name, timeout=timeout)
    print(f"[Lock] acquiring '{name}' ({'redis' if REDIS_URL else 'file'})…")
    lock.acquire()
    print(f"[Lock] acquired '{name}'")
    try:
        yield
    finally:
        lock.release()
        print(f"[Lock] released '{name}'")


__all__ = [
    "notion_lock",
    "make_lock",
    "FileProcessLock",
    "RedisProcessLock",
    "LockTimeoutError",
]
