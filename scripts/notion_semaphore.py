#!/usr/bin/env python3
"""
Distributed semaphore for Notion API workers.
Allows up to N concurrent holders (exclusive lock is N=1).

Backends:
  - file (default): N flock slot files under NOTION_LOCK_DIR
  - redis: ZSET tokens when NOTION_LOCK_REDIS_URL is set

Usage:
    from notion_semaphore import notion_semaphore
    with notion_semaphore("api", limit=2):
        call_notion()
"""
from __future__ import annotations

import atexit
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_DIR = Path(os.environ.get("NOTION_LOCK_DIR", "/tmp/stargate-notion-locks"))
LOCK_TIMEOUT = float(os.environ.get("NOTION_LOCK_TIMEOUT", "600"))
DEFAULT_LIMIT = int(os.environ.get("NOTION_SEM_LIMIT", "2"))
REDIS_URL = os.environ.get("NOTION_LOCK_REDIS_URL", "").strip()
REDIS_TTL = int(os.environ.get("NOTION_LOCK_REDIS_TTL", "900"))


class SemaphoreTimeoutError(TimeoutError):
    pass


class FileSemaphore:
    def __init__(self, name: str, limit: int = DEFAULT_LIMIT, timeout: float = LOCK_TIMEOUT):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.name = name
        self.limit = limit
        self.timeout = timeout
        self._slot_dir = LOCK_DIR / f"sem-{name}"
        self._fd: int | None = None
        self._slot: int | None = None

    def acquire(self) -> int:
        import fcntl

        self._slot_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            for i in range(self.limit):
                path = self._slot_dir / f"slot-{i}.lock"
                path.touch(exist_ok=True)
                fd = os.open(str(path), os.O_RDWR)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.ftruncate(fd, 0)
                    os.write(fd, f"pid={os.getpid()} slot={i} ts={time.time():.0f}\n".encode())
                    self._fd = fd
                    self._slot = i
                    atexit.register(self.release)
                    return i
                except BlockingIOError:
                    os.close(fd)
            if time.monotonic() >= deadline:
                raise SemaphoreTimeoutError(
                    f"Semaphore '{self.name}' full (limit={self.limit}) after {self.timeout}s"
                )
            time.sleep(0.2)

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
        self._slot = None
        try:
            atexit.unregister(self.release)
        except Exception:
            pass

    def __enter__(self) -> "FileSemaphore":
        self.acquire()
        return self

    def __exit__(self, *args) -> None:
        self.release()


class RedisSemaphore:
    def __init__(self, name: str, limit: int = DEFAULT_LIMIT, timeout: float = LOCK_TIMEOUT, ttl: int = REDIS_TTL):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.name = name
        self.limit = limit
        self.timeout = timeout
        self.ttl = ttl
        self._key = f"notion-sem:{name}"
        self._token = f"{os.getpid()}-{uuid.uuid4().hex}"
        self._redis = None

    def _client(self):
        if self._redis is None:
            try:
                import redis
            except ImportError as e:
                raise RuntimeError("pip install redis") from e
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    def acquire(self) -> str:
        r = self._client()
        deadline = time.monotonic() + self.timeout
        script = """
        local key = KEYS[1]
        local token = ARGV[1]
        local limit = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local exp = tonumber(ARGV[4])
        redis.call('zremrangebyscore', key, '-inf', now)
        local n = redis.call('zcard', key)
        if n < limit then
            redis.call('zadd', key, exp, token)
            return 1
        end
        return 0
        """
        while True:
            now = time.time()
            if r.eval(script, 1, self._key, self._token, self.limit, now, now + self.ttl):
                atexit.register(self.release)
                return self._token
            if time.monotonic() >= deadline:
                raise SemaphoreTimeoutError(
                    f"Redis semaphore '{self.name}' full (limit={self.limit}) after {self.timeout}s"
                )
            time.sleep(0.2)

    def release(self) -> None:
        if self._redis is None:
            return
        try:
            self._redis.zrem(self._key, self._token)
        except Exception:
            pass
        try:
            atexit.unregister(self.release)
        except Exception:
            pass

    def __enter__(self) -> "RedisSemaphore":
        self.acquire()
        return self

    def __exit__(self, *args) -> None:
        self.release()


def make_semaphore(name: str, limit: int | None = None, timeout: float | None = None):
    limit = DEFAULT_LIMIT if limit is None else limit
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    if REDIS_URL:
        return RedisSemaphore(name, limit=limit, timeout=timeout)
    return FileSemaphore(name, limit=limit, timeout=timeout)


@contextmanager
def notion_semaphore(
    name: str = "notion-api",
    limit: int | None = None,
    timeout: float | None = None,
) -> Iterator[None]:
    limit = DEFAULT_LIMIT if limit is None else limit
    backend = "redis" if REDIS_URL else "file"
    sem = make_semaphore(name, limit=limit, timeout=timeout)
    print(f"[Semaphore] acquiring '{name}' limit={limit} ({backend})…")
    slot = sem.acquire()
    print(f"[Semaphore] acquired '{name}' slot={slot}")
    try:
        yield
    finally:
        sem.release()
        print(f"[Semaphore] released '{name}'")


__all__ = [
    "notion_semaphore",
    "make_semaphore",
    "FileSemaphore",
    "RedisSemaphore",
    "SemaphoreTimeoutError",
]
