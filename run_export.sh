#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
set -a; source ./secrets.env; set +a
python3 scripts/export_notion_to_csv.py
ls -la notion-templates/
