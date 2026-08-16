#!/usr/bin/env python3
from __future__ import annotations
import csv, os, random, sys, time
from pathlib import Path
from typing import Any
import requests

NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes", "")

def env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v: return v
    return ""

DATABASES = {
    "episodes": {"id": env("NOTION_EPISODES_DATA_SOURCE_ID", "NOTION_EPISODES_DS"), "csv": "Episodes.csv"},
    "characters": {"id": env("NOTION_CHARACTERS_DATA_SOURCE_ID", "NOTION_CHARACTERS_DS"), "csv": "Characters.csv"},
    "ships": {"id": env("NOTION_SHIPS_DATA_SOURCE_ID", "NOTION_SHIPS_DS"), "csv": "Ships.csv"},
    "tech": {"id": env("NOTION_TECH_DATA_SOURCE_ID", "NOTION_TECH_DS"), "csv": "Technologies.csv"},
    "locations": {"id": env("NOTION_LOCATIONS_DATA_SOURCE_ID", "NOTION_LOCATIONS_DS"), "csv": "Locations.csv"},
    "continuity": {"id": env("NOTION_CONTINUITY_DATA_SOURCE_ID", "NOTION_CONTINUITY_DS"), "csv": "Continuity_Issues.csv"},
}
TARGETS = [t.strip() for t in os.environ.get("SYNC_TARGETS", "episodes,characters,ships,tech,locations,continuity").split(",") if t.strip()]

def find_templates() -> Path:
    here = Path(__file__).resolve().parent
    for p in [here / "notion-templates", Path.cwd() / "notion-templates"]:
        if p.is_dir(): return p
    return here / "notion-templates"

TEMPLATE_DIR = find_templates()

class Backoff:
    def __init__(self, max_attempts: int = 6): self.max_attempts = max_attempts
    def delay(self, attempt: int, throttle: bool) -> float:
        base = 1.0 if throttle else 0.2
        d = min(32.0, base * (2 ** (attempt - 1)))
        return random.uniform(0, d) if attempt <= 3 else d / 2 + random.uniform(0, d / 2)
    def run(self, fn, *a, **kw):
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try: return fn(*a, **kw)
            except Exception as e:
                last = e
                if attempt >= self.max_attempts: break
                msg = str(e).lower()
                throttle = any(x in msg for x in ("429", "rate", "503", "529"))
                w = self.delay(attempt, throttle)
                print(f"  [backoff {attempt}] {e} → {w:.1f}s"); time.sleep(w)
        raise RuntimeError(last)

backoff = Backoff()

def headers():
    return {"Authorization": f"Bearer {TOKEN}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}

def api(method, url, **kwargs):
    r = requests.request(method, url, headers=headers(), timeout=60, **kwargs)
    if r.status_code == 429:
        raise RuntimeError(f"rate_limited 429 retry_after={r.headers.get('Retry-After', '2')}")
    if r.status_code >= 400:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else {}

def load_csv(name):
    path = TEMPLATE_DIR / name
    if not path.exists():
        print(f"  Missing: {path}"); return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def title_prop(v): return {"title": [{"type": "text", "text": {"content": (v or "Untitled")[:2000]}}]}
def text_prop(v): return {"rich_text": [{"type": "text", "text": {"content": (v or "")[:2000]}}]}
def select_prop(v): return {"select": {"name": v} if v else None}
def number_prop(v):
    try: return {"number": int(v)}
    except Exception:
        try: return {"number": float(v)}
        except Exception: return {"number": None}

def row_to_props(row):
    name = row.get("Name") or row.get("Title") or row.get("GitHub ID") or "Untitled"
    props = {"Name": title_prop(name)}
    if row.get("GitHub ID"): props["GitHub ID"] = text_prop(row["GitHub ID"])
    for col in ("Episode","Title","Season Title","Primary Setting","Core Technology","Strategic Milestone","Notes","Role / Affiliation","Arc Summary","Key Relationships","Major Seasons","Type","Dimensions","Key Systems","Primary Role","First Appearance / Notes","Origin","Primary Function","Key Parameters / Laws","First Major Use","Galaxy / System","Key Features","Strategic Importance","Related Episode(s)","Related Character / Tech / Location","Resolution Notes"):
        if col in row and str(row.get(col) or "").strip():
            props[col] = text_prop(str(row[col]))
    if "Season" in row and str(row.get("Season") or "").isdigit():
        props["Season"] = number_prop(row["Season"])
    if "Duration (min)" in row: props["Duration (min)"] = number_prop(row["Duration (min)"])
    elif "Duration_Minutes" in row: props["Duration (min)"] = number_prop(row["Duration_Minutes"])
    for sel in ("Canon Status","Source","Status","Severity"):
        if sel in row and str(row.get(sel) or "").strip():
            props[sel] = select_prop(str(row[sel]).strip())
    return props

def existing_ids(database_id):
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    out, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor: body["start_cursor"] = cursor
        data = backoff.run(api, "POST", url, json=body)
        for page in data.get("results", []):
            prop = page.get("properties", {}).get("GitHub ID") or {}
            gid = ""
            if prop.get("type") == "rich_text":
                gid = "".join(t.get("plain_text", "") for t in prop.get("rich_text") or [])
            elif prop.get("type") == "title":
                gid = "".join(t.get("plain_text", "") for t in prop.get("title") or [])
            if gid.strip(): out[gid.strip()] = page["id"]
        if not data.get("has_more"): break
        cursor = data.get("next_cursor"); time.sleep(0.25)
    return out

def create_page(database_id, properties):
    backoff.run(api, "POST", "https://api.notion.com/v1/pages",
                json={"parent": {"database_id": database_id}, "properties": properties})
    time.sleep(0.35)

def update_page(page_id, properties):
    backoff.run(api, "PATCH", f"https://api.notion.com/v1/pages/{page_id}",
                json={"properties": properties})
    time.sleep(0.35)

def sync_one(kind):
    cfg = DATABASES[kind]
    rows, db_id = load_csv(cfg["csv"]), cfg["id"]
    print(f"\n=== {kind} ({cfg['csv']}) ===")
    print(f"  rows={len(rows)}  db={db_id[:8]+'…' if db_id else '(none)'}")
    if not rows: return {"created": 0, "updated": 0, "errors": 0}
    if not db_id:
        print("  skip – set DATA_SOURCE_ID"); return {"created": 0, "updated": 0, "errors": 0}
    if DRY_RUN:
        print(f"  DRY_RUN – would upsert {len(rows)}")
        return {"created": 0, "updated": 0, "errors": 0}
    known = existing_ids(db_id)
    print(f"  existing GitHub IDs: {len(known)}")
    created = updated = errors = 0
    for row in rows:
        gid = (row.get("GitHub ID") or "").strip()
        if not gid: continue
        try:
            props = row_to_props(row)
            if gid in known: update_page(known[gid], props); updated += 1
            else: create_page(db_id, props); created += 1
        except Exception as e:
            errors += 1; print(f"  ERROR {gid}: {e}")
    print(f"  created={created} updated={updated} errors={errors}")
    return {"created": created, "updated": updated, "errors": errors}

def main():
    print("Local Notion Sync – Stargate: The Fifth Race")
    print(f"DRY_RUN={DRY_RUN}  TEMPLATE_DIR={TEMPLATE_DIR}  TOKEN={'yes' if TOKEN else 'NO'}")
    if not TOKEN and not DRY_RUN:
        print("Set NOTION_TOKEN"); return 1
    results = [sync_one(t) for t in TARGETS if t in DATABASES]
    c = sum(r["created"] for r in results)
    u = sum(r["updated"] for r in results)
    e = sum(r["errors"] for r in results)
    print(f"\nDone. created={c} updated={u} errors={e}")
    return 1 if e else 0

if __name__ == "__main__":
    raise SystemExit(main())
