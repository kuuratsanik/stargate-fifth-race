"""Notion API rate limiting — token-style spacing + 429 Retry-After + jitter."""
from __future__ import annotations

import os
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_MIN_INTERVAL = float(os.environ.get("NOTION_MIN_INTERVAL", "0.35"))
DEFAULT_MAX_ATTEMPTS = int(os.environ.get("NOTION_MAX_RETRIES", "8"))
DEFAULT_CAP_SECONDS = float(os.environ.get("NOTION_BACKOFF_CAP", "60"))


class NotionRateLimiter:
    """Serial request pacing + exponential backoff with full/equal jitter."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        cap: float = DEFAULT_CAP_SECONDS,
    ):
        self.min_interval = max(0.05, min_interval)
        self.max_attempts = max(1, max_attempts)
        self.cap = cap
        self._last_request = 0.0
        self._consecutive_429 = 0
        self.stats = {
            "requests": 0,
            "retries": 0,
            "rate_limits": 0,
            "total_wait": 0.0,
        }

    def pace(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request
        interval = self.min_interval * (1.0 + 0.5 * min(self._consecutive_429, 6))
        if elapsed < interval:
            w = interval - elapsed
            time.sleep(w)
            self.stats["total_wait"] += w
        self._last_request = time.monotonic()
        self.stats["requests"] += 1

    def backoff_sleep(self, attempt: int, retry_after: float | None = None, throttle: bool = True) -> float:
        if retry_after is not None and retry_after > 0:
            w = retry_after + random.uniform(0, 0.5)
        else:
            base = 1.0 if throttle else 0.25
            delay = min(self.cap, base * (2 ** (attempt - 1)))
            if attempt <= 3:
                w = random.uniform(0, delay)
            else:
                w = delay / 2 + random.uniform(0, delay / 2)
        time.sleep(w)
        self.stats["total_wait"] += w
        self.stats["retries"] += 1
        return w

    def run(self, fn: Callable[[], T], *, label: str = "") -> T:
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.pace()
            try:
                result = fn()
                self._consecutive_429 = max(0, self._consecutive_429 - 1)
                return result
            except Exception as e:
                last = e
                msg = str(e).lower()
                is_429 = "429" in msg or "rate_limited" in msg or "rate limit" in msg
                is_transient = is_429 or any(
                    x in msg for x in ("503", "529", "502", "timeout", "connection")
                )
                if "validation_error" in msg or "is expected to be" in msg:
                    break
                if attempt >= self.max_attempts or not is_transient:
                    break
                retry_after = None
                if "retry_after=" in msg:
                    try:
                        retry_after = float(msg.split("retry_after=")[1].split()[0])
                    except (IndexError, ValueError):
                        pass
                if is_429:
                    self._consecutive_429 += 1
                    self.stats["rate_limits"] += 1
                w = self.backoff_sleep(attempt, retry_after, throttle=is_429)
                tag = label or "request"
                print(f"[RateLimit] {tag} attempt {attempt}/{self.max_attempts}: {e} → sleep {w:.2f}s")
        raise RuntimeError(f"Failed after {self.max_attempts} attempts: {last}") from last

    def summary(self) -> str:
        s = self.stats
        return (
            f"requests={s['requests']} retries={s['retries']} "
            f"rate_limits={s['rate_limits']} wait={s['total_wait']:.1f}s"
        )


limiter = NotionRateLimiter()
