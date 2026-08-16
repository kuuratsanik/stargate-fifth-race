#!/usr/bin/env python3
"""Notion API helpers: rate limiting, retries, cursor pagination."""
from __future__ import annotations

import os
import random
import time
from typing import Any, Callable, Iterator, TypeVar

try:
    import requests
except ImportError as e:
    raise SystemExit("pip install requests") from e

T = TypeVar("T")

NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
DEFAULT_MIN_INTERVAL = float(os.environ.get("NOTION_MIN_INTERVAL", "0.35"))
DEFAULT_MAX_ATTEMPTS = int(os.environ.get("NOTION_MAX_RETRIES", "8"))
DEFAULT_CAP_SECONDS = float(os.environ.get("NOTION_BACKOFF_CAP", "60"))
DEFAULT_PAGE_SIZE = int(os.environ.get("NOTION_PAGE_SIZE", "100"))


class NotionRateLimiter:
    """Pace requests (~3/s), honor 429 Retry-After, exponential jitter backoff."""

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
            "pages": 0,
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

    def backoff_sleep(
        self,
        attempt: int,
        retry_after: float | None = None,
        throttle: bool = True,
    ) -> float:
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
                is_429 = any(x in msg for x in ("429", "rate_limited", "rate limit"))
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
                print(
                    f"[RateLimit] {label or 'request'} "
                    f"attempt {attempt}/{self.max_attempts}: {e} → sleep {w:.2f}s"
                )
        raise RuntimeError(f"Failed after {self.max_attempts} attempts: {last}") from last

    def summary(self) -> str:
        s = self.stats
        return (
            f"requests={s['requests']} pages={s['pages']} retries={s['retries']} "
            f"rate_limits={s['rate_limits']} wait={s['total_wait']:.1f}s"
        )


limiter = NotionRateLimiter()


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(
    method: str,
    url: str,
    token: str,
    *,
    json_body: dict | None = None,
    rl: NotionRateLimiter | None = None,
    label: str = "",
) -> dict:
    rl = rl or limiter

    def _do() -> dict:
        r = requests.request(
            method, url, headers=notion_headers(token), json=json_body, timeout=60
        )
        if r.status_code == 429:
            ra = r.headers.get("Retry-After", "2")
            raise RuntimeError(f"rate_limited 429 retry_after={ra}")
        if r.status_code >= 400:
            raise RuntimeError(f"Notion {r.status_code}: {r.text[:500]}")
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    return rl.run(_do, label=label or method)


def paginate(
    url: str,
    token: str,
    *,
    body: dict | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    rl: NotionRateLimiter | None = None,
    label: str = "paginate",
) -> list[dict]:
    """Cursor-paginate until has_more is false. Raises on 10k incomplete cap."""
    rl = rl or limiter
    page_size = max(1, min(100, page_size))
    results: list[dict] = []
    cursor: str | None = None
    base_body = dict(body or {})

    while True:
        payload = {**base_body, "page_size": page_size}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", url, token, json_body=payload, rl=rl, label=label)
        rl.stats["pages"] += 1
        status = data.get("request_status") or {}
        if status.get("type") == "incomplete":
            reason = status.get("incomplete_reason", "unknown")
            raise RuntimeError(
                f"Notion query incomplete ({reason}) — hit result cap; split filter/sort windows"
            )
        results.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return results


def paginate_iter(
    url: str,
    token: str,
    *,
    body: dict | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    rl: NotionRateLimiter | None = None,
    label: str = "paginate",
) -> Iterator[dict]:
    for item in paginate(url, token, body=body, page_size=page_size, rl=rl, label=label):
        yield item


__all__ = [
    "NotionRateLimiter",
    "limiter",
    "notion_headers",
    "notion_request",
    "paginate",
    "paginate_iter",
    "NOTION_VERSION",
]
