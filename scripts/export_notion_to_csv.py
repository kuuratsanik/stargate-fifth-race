#!/usr/bin/env python3
"""Export Notion databases → notion-templates/*.csv (CI + local)."""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_TOKEN", "").strip()

def env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""

DATABASES = {
    "Episodes.csv": {
        "id": env("NOTION_EPISODES_DATA_SOURCE_ID", "NOTION_EPISODES_DS"),
        "columns": [
            "Name", "GitHub ID", "Episode", "Season", "Season Title", "Title",
            "Duration (min)", "Primary Setting", "Core Technology",
            "Strategic Milestone", "Canon Status", "Source", "Status", "Notes",
        ],
        "sort_key": "Episode",
    },
    "Characters.csv": {
        "id": env("NOTION_CHARACTERS_DATA_SOURCE_ID", "NOTION_CHARACTERS_DS"),
        "columns": [
            "Name", "GitHub ID", "Role / Affiliation", "Arc Summary",
            "Key Relationships", "Major Seasons", "Status", "Source",
            "Canon Status", "Notes",
        ],
        "sort_key": "Name",
    },
    "Ships.csv": {
        "id": env("NOTION_SHIPS_DATA_SOURCE_ID", "NOTION_SHIPS_DS"),
        "columns": [
            "Name", "GitHub ID", "Type", "Dimensions", "Key Systems",
            "Primary Role", "First Appearance / Notes", "Source", "Canon Status",
        ],
        "sort_key": "Name",
    },
    "Technologies.csv": {
        "id": env("NOTION_TECH_DATA_SOURCE_ID", "NOTION_TECH_DS"),
        "columns": [
            "Name", "GitHub ID", "Origin", "Primary Function",
            "Key Parameters / Laws", "First Major Use", "Source", "Canon Status",
        ],
        "sort_key": "Name",
    },
    "Locations.csv": {
        "id": env("NOTION_LOCATIONS_DATA_SOURCE_ID", "NOTION_LOCATIONS_DS"),
        "columns": [
            "Name", "GitHub ID", "Galaxy / System", "Type", "Key Features",
            "Strategic Importance", "Major Seasons", "Source", "Canon Status",
        ],
        "sort_key": "Name",
    },
    "Continuity_Issues.csv": {
        "id": env("NOTION_CONTINUITY_DATA_SOURCE_ID", "NOTION_CONTINUITY_DS"),
        "columns": [
            "Name", "GitHub ID", "Related Episode(s)",
            "Related Character / Tech / Location", "Severity", "Status",
            "Resolution Notes", "Source", "Canon Status",
        ],
        "sort_key": "GitHub ID",
    },
}

EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", "notion-templates"))
ONLY = [x.strip() for x in os.environ.get("EXPORT_ONLY", "").split(",") if x.strip()]


def headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def plain(prop: dict | None) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title") or [])
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text") or [])
    if t == "number":
        v = prop.get("number")
        if v is None:
            return ""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)
    if t == "select":
        s = prop.get("select")
        return s["name"] if s else ""
    if t == "status":
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "multi_select":
        return ", ".join(x.get("name", "") for x in prop.get("multi_select") or [])
    return ""


def query_all(database_id: str) -> list:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    pages = []
    cursor = None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(url, headers=headers(), json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Notion {r.status_code}: {r.text[:400]}")
        data = r.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(0.25)
    return pages


def page_to_row(page: dict, columns: list) -> dict:
    props = page.get("properties", {})
    row = {col: plain(props.get(col)) for col in columns}
    if not row.get("Name"):
        for k, v in props.items():
            if v.get("type") == "title":
                row["Name"] = plain(v)
                break
    return row


def sort_rows(rows: list, key: str) -> list:
    def sk(r: dict):
        v = r.get(key) or r.get("GitHub ID") or r.get("Name") or ""
        try:
            return (0, int(v))
        except ValueError:
            return (1, str(v).lower())
    return sorted(rows, key=sk)


def export_one(filename: str, cfg: dict) -> int:
    db_id = cfg["id"]
    print(f"\n=== {filename} ===")
    if not db_id:
        print("  skip – no database id")
        return 0
    pages = query_all(db_id)
    rows = sort_rows([page_to_row(p, cfg["columns"]) for p in pages], cfg["sort_key"])
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / filename
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cfg["columns"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)")
    return len(rows)


def main() -> int:
    print("Notion → CSV export")
    print(f"TOKEN={'yes' if TOKEN else 'NO'} EXPORT_DIR={EXPORT_DIR}")
    if not TOKEN:
        print("Set NOTION_TOKEN")
        return 1
    targets = DATABASES
    if ONLY:
        targets = {
            k: v for k, v in DATABASES.items()
            if k in ONLY or k.replace(".csv", "") in ONLY
        }
    total = errors = 0
    for filename, cfg in targets.items():
        try:
            total += export_one(filename, cfg)
        except Exception as e:
            errors += 1
            print(f"  ERROR: {e}")
    print(f"\nDone. total_rows={total} errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
