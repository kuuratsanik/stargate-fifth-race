# Local Git + Notion sync (no GitHub Actions)

GitHub is the file archive. Notion is the working bible. Sync runs only on your PC.

## Push everything to GitHub (no Actions)

```bash
cd ~/Projektid/stargate-fifth-race
source .venv/bin/activate
set -a; source ./secrets.env; set +a

# 1) Refresh CSVs from Notion
./run_export.sh

# 2) Commit and push
git add -A
git status
git commit -m "canon: export from Notion + continuity locks"
git push -u origin main
```

If branch diverged:

```bash
git pull origin main --rebase
git push origin main
```

## Pull from GitHub then sync to Notion

```bash
git pull origin main
./run_sync_dry.sh
./run_sync_live.sh
```

## Daily loop (optional cron — export only)

```cron
0 6 * * * cd $HOME/Projektid/stargate-fifth-race && . .venv/bin/activate && set -a && . ./secrets.env && set +a && python3 scripts/export_notion_to_csv.py >> /tmp/sfr-export.log 2>&1
```

Review, then `git add` / `commit` / `push` yourself.

## Disable Actions noise (optional)

Repo → Settings → Actions → General → Disable actions for this repository

Workflow YAML files can stay in the repo; they do nothing while disabled/billing-locked.

## Auth for git push

```bash
gh auth login
# or SSH:
git remote set-url origin git@github.com:kuuratsanik/stargate-fifth-race.git
```
