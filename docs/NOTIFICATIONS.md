# Notifications Setup

## Discord
1. Server → Integrations → Webhooks → New Webhook
2. Copy URL
3. Add GitHub secret: `DISCORD_WEBHOOK`

## Slack
1. Create Incoming Webhook app
2. Add GitHub secret: `SLACK_WEBHOOK`

The sync script and workflow already post a simple success/failure message when either secret is present.

## Suggested messages
- ✅ Canon sync OK
- ❌ Canon sync FAILED: {error}
- Optional: include validation error count from the artifact
