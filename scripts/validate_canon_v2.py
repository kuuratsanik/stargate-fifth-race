#!/usr/bin/env python3
"""
Stargate: The Fifth Race – Canon Validator v2
Validates Master Index + supporting CSVs.
Designed for GitHub Actions and local pre-commit.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "00-canon" / "Master_Index.csv",
    Path("/home/workdir/artifacts/Stargate_The_Fifth_Race_Master_Index.csv"),
    Path("/home/workdir/artifacts/Expanded_Materials/notion-templates/Episodes.csv"),
]

REQUIRED_COLUMNS_MASTER = {
    "Season", "Season_Title", "Episode", "Duration_Minutes",
    "Title", "Primary_Setting", "Core_Technology_Asset",
    "Strategic_Milestone_Plot_Impact",
}

REQUIRED_COLUMNS_EPISODES_NOTION = {
    "Name", "GitHub ID", "Episode", "Season", "Title",
    "Duration (min)", "Primary Setting", "Core Technology",
    "Strategic Milestone", "Canon Status", "Source",
}

errors: list[str] = []
warnings: list[str] = []


def log(msg: str, level: str = "ERROR") -> None:
    line = f"[{level}] {msg}"
    print(line)
    (errors if level == "ERROR" else warnings).append(line)


def find_index() -> Path | None:
    for p in CANDIDATES:
        if p.exists():
            return p
    return None


def validate_master(path: Path) -> None:
    print(f"Validating: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = set(reader.fieldnames or [])

    if "GitHub ID" in fields:
        required = REQUIRED_COLUMNS_EPISODES_NOTION
        ep_key, title_key, dur_key = "Episode", "Title", "Duration (min)"
    else:
        required = REQUIRED_COLUMNS_MASTER
        ep_key, title_key, dur_key = "Episode", "Title", "Duration_Minutes"

    missing = required - fields
    if missing:
        log(f"Missing columns: {sorted(missing)}")

    if not rows:
        log("Index is empty")
        return

    episode_ids = []
    seasons = defaultdict(list)

    for i, row in enumerate(rows, start=2):
        ep = (row.get(ep_key) or "").strip()
        title = (row.get(title_key) or "").strip()
        duration = (row.get(dur_key) or "").strip()
        season = (row.get("Season") or "").strip()

        if not ep:
            log(f"Line {i}: missing Episode")
            continue
        if not title:
            log(f"Line {i}: Episode {ep} has empty Title")

        episode_ids.append(ep)
        seasons[season].append(ep)

        if duration:
            try:
                d = int(duration)
                if d < 30 or d > 90:
                    log(f"Line {i}: Episode {ep} unusual duration {d}", "WARN")
            except ValueError:
                log(f"Line {i}: Episode {ep} non-integer duration '{duration}'")

    counts = Counter(episode_ids)
    dupes = [e for e, c in counts.items() if c > 1]
    if dupes:
        log(f"Duplicate Episode IDs: {dupes}")

    if len(episode_ids) != 200:
        log(f"Expected 200 episodes, found {len(episode_ids)}", "WARN")

    for s, eps in sorted(seasons.items()):
        if s and len(eps) != 20:
            log(f"Season {s} has {len(eps)} episodes (expected 20)", "WARN")

    print(f"Rows: {len(rows)} | Unique episodes: {len(counts)} | Seasons: {len(seasons)}")


def main() -> int:
    path = find_index()
    if not path:
        log("No Master Index / Episodes CSV found in known locations")
        return 1

    validate_master(path)

    print("\n--- Summary ---")
    print(f"Errors:   {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    report = ROOT / "validation-report.txt"
    report.write_text(
        "\n".join(errors + warnings) or "No issues found.\n",
        encoding="utf-8",
    )
    print(f"Report written to {report}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
