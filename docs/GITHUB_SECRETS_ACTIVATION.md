# GitHub Secrets – Activation Checklist

You must add these in your private GitHub repo:

**Settings → Secrets and variables → Actions → New repository secret**

## Required Secrets

| Secret Name | Value | Where to find |
|-------------|-------|---------------|
| `NOTION_TOKEN` | `ntn_...` (your integration token) | Notion → My integrations → Fifth Race Canon Sync |
| `NOTION_EPISODES_DATA_SOURCE_ID` | `1cb8794a-b6dc-4ce8-a62d-1e3f55735ff4` | Or from Episodes DB → `e011c697-fd50-4d3b-bc88-80c3a3b591ba` |
| `NOTION_CHARACTERS_DATA_SOURCE_ID` | `45eb20dc-b26b-4dbb-a902-2213dcf19367` | Characters database |
| `NOTION_SHIPS_DATA_SOURCE_ID` | `20ce3fa8-8cec-4319-b00b-3a3424f8754c` | Ships database |
| `NOTION_TECH_DATA_SOURCE_ID` | `844de51c-153b-46bb-8106-def70640b740` | Technologies database |
| `NOTION_LOCATIONS_DATA_SOURCE_ID` | `bdf9a0ea-9bb3-4441-a6ce-14eea423c74e` | Locations database |
| `NOTION_CONTINUITY_DATA_SOURCE_ID` | `da778496-fdee-4b03-a311-06da50b122b5` | Continuity Issues data source |

## Optional Notification Secrets

| Secret Name | Value |
|-------------|-------|
| `DISCORD_WEBHOOK` | `https://discord.com/api/webhooks/...` |
| `SLACK_WEBHOOK` | `https://hooks.slack.com/services/...` |

## Steps
1. Add every secret above
2. Share Notion integration with Working Bible + all 6 databases
3. Run workflow manually once with `dry_run = true`
