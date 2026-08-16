#!/usr/bin/env python3
"""Stargate Fifth Race – Notion Sync (schema-aware property types)."""
from __future__ import annotations

import csv
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes", "")
WEBHOOK = (os.environ.get("DISCORD_WEBHOOK") or os.environ.get("SLACK_WEBHOOK") or "").strip()

def _ds(*keys: str) -> str:
    for k in keys:
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""

DATABASES = {
    "episodes": {"id": _ds("NOTION_EPISODES_DS", "NOTION_EPISODES_DATA_SOURCE_ID"), "csv": "Episodes.csv", "key": "GitHub ID"},
    "characters": {"id": _ds("NOTION_CHARACTERS_DS", "NOTION_CHARACTERS_DATA_SOURCE_ID"), "csv": "Characters.csv", "key": "GitHub ID"},
    "ships": {"id": _ds("NOTION_SHIPS_DS", "NOTION_SHIPS_DATA_SOURCE_ID"), "csv": "Ships.csv", "key": "GitHub ID"},
    "tech": {"id": _ds("NOTION_TECH_DS", "NOTION_TECH_DATA_SOURCE_ID"), "csv": "Technologies.csv", "key": "GitHub ID"},
    "locations": {"id": _ds("NOTION_LOCATIONS_DS", "NOTION_LOCATIONS_DATA_SOURCE_ID"), "csv": "Locations.csv", "key": "GitHub ID"},
    "continuity": {"id": _ds("NOTION_CONTINUITY_DS", "NOTION_CONTINUITY_DATA_SOURCE_ID"), "csv": "Continuity_Issues.csv", "key": "GitHub ID"},
}

TARGETS = [t.strip() for t in os.environ.get(
    "SYNC_TARGETS", "episodes,characters,ships,tech,locations,continuity"
).split(",") if t.strip()]


def template_dir() -> Path:
    candidates = [
        Path("notion-templates"),
        Path(__file__).resolve().parents[1] / "notion-templates",
        Path(__file__).resolve().parent / "notion-templates",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


TEMPLATE_DIR = template_dir()
_SCHEMA_CACHE: dict[str, dict[str, str]] = {}


class Backoff:
    def __init__(self, max_attempts: int = 6):
        self.max_attempts = max_attempts

    def wait(self, attempt: int, throttle: bool = True) -> float:
        base = 1.0 if throttle else 0.2
        delay = min(32.0, base * (2 ** (attempt - 1)))
        if attempt <= 3:
            return random.uniform(0, delay)
        return delay / 2 + random.uniform(0, delay / 2)

    def run(self, fn, *args, **kwargs):
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last = e
                msg = str(e).lower()
                if attempt >= self.max_attempts:
                    break
                if "validation_error" in msg or "is expected to be" in msg:
                    break
                throttle = any(x in msg for x in ("429", "rate", "throttle", "529", "503"))
                w = self.wait(attempt, throttle)
                print(f"[Backoff] attempt {attempt}/{self.max_attempts}: {e} → sleep {w:.2f}s")
                time.sleep(w)
        raise RuntimeError(f"Failed after retries: {last}") from last


backoff = Backoff()


def headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notify(text: str) -> None:
    print(f"[Notify] {text}")
    if not WEBHOOK:
        return
    try:
        requests.post(WEBHOOK, json={"content": text, "text": text}, timeout=15)
    except Exception as e:
        print(f"[Notify] webhook error: {e}")


def notion_request(method: str, url: str, **kwargs) -> dict:
    r = requests.request(method, url, headers=headers(), timeout=60, **kwargs)
    if r.status_code == 429:
        raise RuntimeError(f"rate_limited 429 retry_after={r.headers.get('Retry-After', '2')}")
    if r.status_code >= 400:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:500]}")
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


def load_csv(name: str) -> list:
    path = TEMPLATE_DIR / name
    if not path.exists():
        print(f"  Missing CSV: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_schema(database_id: str) -> dict:
    if database_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[database_id]
    data = backoff.run(lambda: notion_request("GET", f"https://api.notion.com/v1/databases/{database_id}"))
    props = data.get("properties") or {}
    schema = {name: (meta.get("type") or "") for name, meta in props.items()}
    _SCHEMA_CACHE[database_id] = schema
    print(f"  schema: {len(schema)} properties → {sorted(set(schema.values()))}")
    return schema


def encode_value(prop_type: str, value: str):
    value = (value or "").strip()
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": (value or "Untitled")[:2000]}}]}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}
    if prop_type == "number":
        try:
            return {"number": float(value) if "." in value else int(value)}
        except ValueError:
            return {"number": None}
    if prop_type == "select":
        return {"select": {"name": value[:100]} if value else None}
    if prop_type == "multi_select":
        if not value:
            return {"multi_select": []}
        parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        return {"multi_select": [{"name": p[:100]} for p in parts]}
    if prop_type == "status":
        return {"status": {"name": value[:100]} if value else None}
    if prop_type == "checkbox":
        return {"checkbox": value.lower() in ("1", "true", "yes", "y")}
    if prop_type == "url":
        return {"url": value or None}
    if prop_type == "email":
        return {"email": value or None}
    if prop_type == "date":
        return {"date": {"start": value} if value else None}
    return None


def row_to_properties(row: dict, schema: dict) -> dict:
    props = {}
    title_keys = [k for k, t in schema.items() if t == "title"]
    title_name = title_keys[0] if title_keys else "Name"
    title_val = row.get("Name") or row.get("Title") or row.get("GitHub ID") or "Untitled"
    props[title_name] = encode_value("title", title_val)
    for col, raw in row.items():
        if col not in schema or schema[col] == "title":
            continue
        if raw is None or str(raw).strip() == "":
            continue
        enc = encode_value(schema[col], str(raw))
        if enc is not None:
            props[col] = enc
    return props


def query_existing_ids(database_id: str, schema: dict, key_prop: str = "GitHub ID") -> dict:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    out, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = backoff.run(lambda: notion_request("POST", url, json=body))
        for page in data.get("results", []):
            props = page.get("properties", {})
            key_field = props.get(key_prop) or props.get("GitHub ID") or {}
            gid, t = "", key_field.get("type") or schema.get(key_prop, "rich_text")
            if t == "rich_text":
                gid = "".join(x.get("plain_text", "") for x in key_field.get("rich_text") or [])
            elif t == "title":
                gid = "".join(x.get("plain_text", "") for x in key_field.get("title") or [])
            elif t == "select":
                gid = (key_field.get("select") or {}).get("name") or ""
            if gid:
                out[gid.strip()] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(0.25)
    return out


def create_page(database_id: str, properties: dict) -> str:
    data = backoff.run(lambda: notion_request(
        "POST", "https://api.notion.com/v1/pages",
        json={"parent": {"database_id": database_id}, "properties": properties},
    ))
    time.sleep(0.35)
    return data.get("id", "")


def update_page(page_id: str, properties: dict) -> None:
    backoff.run(lambda: notion_request(
        "PATCH", f"https://api.notion.com/v1/pages/{page_id}",
        json={"properties": properties},
    ))
    time.sleep(0.35)


def sync_database(kind: str) -> dict:
    cfg = DATABASES[kind]
    db_id, rows = cfg["id"], load_csv(cfg["csv"])
    print(f"\n=== Sync {kind} ({cfg['csv']}) ===")
    print(f"  CSV rows: {len(rows)}")
    empty = {"kind": kind, "csv": len(rows), "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    if not rows:
        return empty
    if not db_id:
        print("  No database id – skip"); return {**empty, "skipped": len(rows)}
    if DRY_RUN:
        print(f"  DRY_RUN: would upsert {len(rows)} → {db_id[:8]}…")
        return {**empty, "skipped": len(rows), "dry_run": True}

    schema = get_schema(db_id)
    missing = set(rows[0].keys()) - set(schema.keys())
    if missing:
        print(f"  CSV columns not in Notion schema (skipped): {sorted(missing)}")

    existing = query_existing_ids(db_id, schema, cfg["key"])
    print(f"  Existing with GitHub ID: {len(existing)}")
    created = updated = skipped = errors = 0
    for row in rows:
        gid = (row.get(cfg["key"]) or row.get("GitHub ID") or "").strip()
        if not gid:
            skipped += 1
            continue
        try:
            props = row_to_properties(row, schema)
            if gid in existing:
                update_page(existing[gid], props)
                updated += 1
            else:
                create_page(db_id, props)
                created += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR {gid}: {e}")
    print(f"  created={created} updated={updated} skipped={skipped} errors={errors}")
    return {"kind": kind, "csv": len(rows), "created": created, "updated": updated, "skipped": skipped, "errors": errors}


def main() -> int:
    print("Stargate Fifth Race – Notion Sync (schema-aware)")
    print(f"DRY_RUN={DRY_RUN} TEMPLATE_DIR={TEMPLATE_DIR}")
    print(f"TARGETS={TARGETS} TOKEN={bool(TOKEN)}")
    if not TOKEN and not DRY_RUN:
        notify("Canon sync aborted – missing NOTION_TOKEN"); return 1
    results = [sync_database(k) for k in TARGETS if k in DATABASES]
    c = sum(r.get("created", 0) for r in results)
    u = sum(r.get("updated", 0) for r in results)
    e = sum(r.get("errors", 0) for r in results)
    summary = f"Canon sync {'DRY_RUN ' if DRY_RUN else ''}OK – created={c} updated={u} errors={e}"
    print("\n" + summary)
    notify(("OK " if e == 0 else "WARN ") + summary)
    return 1 if e else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"FATAL: {e}")
        notify(f"Canon sync FATAL: {e}")
        raise SystemExit(1)
