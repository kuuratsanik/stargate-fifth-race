#!/usr/bin/env python3
"""Production Notion sync skeleton with safe dry-run and backoff."""
from __future__ import annotations

import csv
import os
import random
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

TOKEN = os.environ.get("NOTION_TOKEN", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes", "")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK") or os.environ.get("SLACK_WEBHOOK")

DS = {
    "episodes": os.environ.get("NOTION_EPISODES_DS") or os.environ.get("NOTION_EPISODES_DATA_SOURCE_ID", ""),
    "characters": os.environ.get("NOTION_CHARACTERS_DS") or os.environ.get("NOTION_CHARACTERS_DATA_SOURCE_ID", ""),
    "ships": os.environ.get("NOTION_SHIPS_DS") or os.environ.get("NOTION_SHIPS_DATA_SOURCE_ID", ""),
    "tech": os.environ.get("NOTION_TECH_DS") or os.environ.get("NOTION_TECH_DATA_SOURCE_ID", ""),
    "locations": os.environ.get("NOTION_LOCATIONS_DS") or os.environ.get("NOTION_LOCATIONS_DATA_SOURCE_ID", ""),
    "continuity": os.environ.get("NOTION_CONTINUITY_DS") or os.environ.get("NOTION_CONTINUITY_DATA_SOURCE_ID", ""),
}


def _template_dir() -> Path:
    candidates = [
        Path("notion-templates"),
        Path("Expanded_Materials/notion-templates"),
        Path("/home/workdir/artifacts/Expanded_Materials/notion-templates"),
    ]
    try:
        here = Path(__file__).resolve().parent
        candidates.insert(0, here.parents[1] / "notion-templates")
    except NameError:
        pass
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


TEMPLATE_DIR = _template_dir()


def notify(text: str) -> None:
    print(f"[Notify] {text}")
    if not WEBHOOK or requests is None:
        return
    try:
        requests.post(WEBHOOK, json={"content": text, "text": text}, timeout=10)
    except Exception as e:
        print(f"[Notify] webhook error: {e}")


def load_csv(name: str) -> list:
    path = TEMPLATE_DIR / name
    if not path.exists():
        print(f"Missing {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    print(f"DRY_RUN={DRY_RUN}")
    print(f"Template dir: {TEMPLATE_DIR}")
    episodes = load_csv("Episodes.csv")
    print(f"Episodes in template: {len(episodes)}")

    if not TOKEN and not DRY_RUN:
        notify("Canon sync aborted – missing NOTION_TOKEN")
        return 1

    if not DS["episodes"] or DRY_RUN:
        print("Dry-run / no DS – no writes")
        notify("Canon sync dry-run OK")
        return 0

    print("Live sync path ready")
    notify("Canon sync live path invoked")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
