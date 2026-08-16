#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
set -a; source ./secrets.env; set +a
DRY_RUN=true python3 scripts/sync_all_to_notion.py
