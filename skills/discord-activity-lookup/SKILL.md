---
name: discord-activity-lookup
description: Query Drie's recent Discord activity — uses the discord_activity tool for fast queries, falls back to JSONL file reads.
trigger: when the user asks about their recent Discord activity, what they were doing, what songs they played, what games they played, or similar.
---

# Discord Activity Lookup

Use this skill when Drie asks about his past Discord activity — songs played, games played, online status, etc.

## Preferred Method: discord_activity Tool

The `discord_activity` tool is the fastest and cleanest way to query presence data. Use it first.

**Available queries:**
- `discord_activity(query="status")` — current presence (instant, reads last entry)
- `discord_activity(query="timeline", days=N)` — activity periods for the last N days
- `discord_activity(query="stats", days=N)` — aggregated statistics
- `discord_activity(query="spotify", minutes=N)` — recent Spotify listening
- `discord_activity(query="history", minutes=N)` — raw recent entries

## Fallback: Direct JSONL Read

If the tool isn't available or returns an error, read the JSONL files directly.

**File locations:**
- **Daily files (current):** `C:\Users\Drie\AppData\Local\hermes\profiles\aura\logs\discord-activity\YYYY-MM-DD.jsonl`
- **Legacy single file (historical):** `C:\Users\Drie\AppData\Local\hermes\profiles\aura\output\discord-activity.jsonl`

**Approach:**
1. Parse the time period from the user's query
2. For short periods (< 1 day): read the relevant daily file(s)
3. For longer periods: read multiple daily files or use the legacy file
4. Parse entries and filter by timestamp
5. Present a summary: songs, games, status changes, platforms

## Output Format

Always present results clearly:
- Status/online summary
- Spotify songs played (with timestamps or counts)
- Games/activities detected
- Platform usage
- Any notable gaps

For timeline queries, use bullet list with status indicators (🟢/🟡/⚫), HH:MM time ranges (24h, WIB), activities, and Spotify info.
