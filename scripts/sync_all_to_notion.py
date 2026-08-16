#!/usr/bin/env python3
"""Stargate Fifth Race – Automated Notion Sync (GitHub → Notion upsert by GitHub ID)."""
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
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


TEMPLATE_DIR = template_dir()


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
                throttle = any(x in msg for x in ("429", "rate", "throttle", "529", "503"))
                w = self.wait(attempt, throttle)
                print(f"[Backoff] attempt {attempt}/{self.max_attempts}: {e} → sleep {w:.2f}s")
                time.sleep(w)
        raise RuntimeError(f"Failed after {self.max_attempts} attempts: {last}") from last


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
        ra = r.headers.get("Retry-After", "2")
        raise RuntimeError(f"rate_limited 429 retry_after={ra}")
    if r.status_code >= 400:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:400]}")
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


def text_prop(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (value or "")[:2000]}}]}


def title_prop(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": (value or "Untitled")[:2000]}}]}


def select_prop(value: str) -> dict:
    if not value:
        return {"select": None}
    return {"select": {"name": value}}


def number_prop(value: Any) -> dict:
    try:
        return {"number": int(value)}
    except (TypeError, ValueError):
        try:
            return {"number": float(value)}
        except (TypeError, ValueError):
            return {"number": None}


def row_to_properties(row: dict, kind: str) -> dict:
    name = row.get("Name") or row.get("Title") or row.get("GitHub ID") or "Untitled"
    props: dict = {"Name": title_prop(name)}
    if row.get("GitHub ID"):
        props["GitHub ID"] = text_prop(row["GitHub ID"])
    # rich_text fields only — do NOT include Origin/Type (those are select in Notion)
    text_cols = [
        "Episode", "Title", "Season Title", "Primary Setting", "Core Technology",
        "Strategic Milestone", "Notes", "Role / Affiliation", "Arc Summary",
        "Key Relationships", "Major Seasons", "Dimensions", "Key Systems",
        "Primary Role", "First Appearance / Notes", "Primary Function",
        "Key Parameters / Laws", "First Major Use", "Galaxy / System", "Key Features",
        "Strategic Importance", "Related Episode(s)",
        "Related Character / Tech / Location", "Resolution Notes",
    ]
    for col in text_cols:
        if col in row and str(row.get(col) or "").strip():
            props[col] = text_prop(str(row[col]))
    if "Season" in row and str(row["Season"]).strip().isdigit():
        props["Season"] = number_prop(row["Season"])
    if "Duration (min)" in row:
        props["Duration (min)"] = number_prop(row["Duration (min)"])
    elif "Duration_Minutes" in row:
        props["Duration (min)"] = number_prop(row["Duration_Minutes"])
    for sel in ("Canon Status", "Source", "Status", "Severity", "Origin", "Type"):
        if sel in row and str(row.get(sel) or "").strip():
            props[sel] = select_prop(str(row[sel]).strip())
    return props


def query_existing_ids(database_id: str, key_prop: str = "GitHub ID") -> dict:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    out: dict = {}
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        def _q():
            return notion_request("POST", url, json=body)

        data = backoff.run(_q)
        for page in data.get("results", []):
            props = page.get("properties", {})
            key_field = props.get(key_prop) or props.get("GitHub ID")
            gid = ""
            if key_field:
                t = key_field.get("type")
                if t == "rich_text":
                    gid = "".join(x.get("plain_text", "") for x in (key_field.get("rich_text") or []))
                elif t == "title":
                    gid = "".join(x.get("plain_text", "") for x in (key_field.get("title") or []))
            if gid:
                out[gid.strip()] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(0.3)
    return out


def create_page(database_id: str, properties: dict) -> str:
    def _c():
        return notion_request(
            "POST",
            "https://api.notion.com/v1/pages",
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
    data = backoff.run(_c)
    time.sleep(0.35)
    return data.get("id", "")


def update_page(page_id: str, properties: dict) -> None:
    def _u():
        return notion_request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            json={"properties": properties},
        )
    backoff.run(_u)
    time.sleep(0.35)


def sync_database(kind: str) -> dict:
    cfg = DATABASES[kind]
    db_id = cfg["id"]
    rows = load_csv(cfg["csv"])
    print(f"\n=== Sync {kind} ({cfg['csv']}) ===")
    print(f"  CSV rows: {len(rows)}")
    if not rows:
        return {"kind": kind, "csv": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    if not db_id:
        print(f"  No database id – skip")
        return {"kind": kind, "csv": len(rows), "created": 0, "updated": 0, "skipped": len(rows), "errors": 0}
    if DRY_RUN:
        print(f"  DRY_RUN: would upsert {len(rows)} → {db_id[:8]}…")
        return {"kind": kind, "csv": len(rows), "created": 0, "updated": 0, "skipped": len(rows), "errors": 0, "dry_run": True}

    existing = query_existing_ids(db_id, cfg["key"])
    print(f"  Existing with GitHub ID: {len(existing)}")
    created = updated = skipped = errors = 0
    for row in rows:
        gid = (row.get(cfg["key"]) or row.get("GitHub ID") or "").strip()
        if not gid:
            skipped += 1
            continue
        try:
            props = row_to_properties(row, kind)
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
    print("Stargate Fifth Race – Notion Sync")
    print(f"DRY_RUN={DRY_RUN} TEMPLATE_DIR={TEMPLATE_DIR}")
    print(f"TARGETS={TARGETS} TOKEN={bool(TOKEN)}")
    if not TOKEN and not DRY_RUN:
        notify("Canon sync aborted – missing NOTION_TOKEN")
        return 1
    results = []
    for kind in TARGETS:
        if kind in DATABASES:
            results.append(sync_database(kind))
        else:
            print(f"Unknown target: {kind}")
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
