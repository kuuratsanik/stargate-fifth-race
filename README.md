# Stargate: The Fifth Race

Canonical source of truth for the Master Production Bible (Seasons 1–10 / 200 episodes).

## Notion
Working Bible: https://app.notion.com/p/3be9b4ffb7ec81189d05f5fdd59d3667

## Structure
- `00-canon/` – Master Index + Production Bible
- `notion-templates/` – CSVs for Notion
- `scripts/` – export, sync, validate
- `.github/workflows/` – Actions (need billing unlocked)
- `docs/` – secrets checklist, roadmap

## Local ops (works without GitHub Actions)
If Actions fail with a billing lock, run on Ubuntu:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install requests
# export NOTION_TOKEN and the 6 DATA_SOURCE_ID vars
python3 scripts/export_notion_to_csv.py          # Notion → CSV (creates Episodes.csv)
DRY_RUN=true python3 scripts/sync_all_to_notion.py
DRY_RUN=false python3 scripts/sync_all_to_notion.py
```

## Actions (after billing is fixed)
- **Export Notion to CSV** – daily backup Notion → repo
- **Sync Canon to Notion (v2)** – CSV → Notion upsert

Document ID: TDIA-PB-2026-OMNI-01
