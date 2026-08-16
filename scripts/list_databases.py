import os
import requests

token = os.environ.get("NOTION_TOKEN")
if not token:
    print("ERROR: NOTION_TOKEN is empty. Check secrets.env.")
    exit(1)

headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

res = requests.post(
    "https://api.notion.com/v1/search",
    headers=headers,
    json={"filter": {"value": "database", "property": "object"}}
)

data = res.json()
if "results" not in data:
    print("Notion API Error:", data)
    exit(1)

print("\n--- Accessible Notion Databases ---")
for db in data.get("results", []):
    title_list = db.get("title", [])
    title = "".join([t.get("plain_text", "") for t in title_list]) or "[Untitled]"
    db_id = db.get("id")
    print(f"Name: {title}")
    print(f"ID:   {db_id}\n")
