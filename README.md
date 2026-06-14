# hermes-discord-activity-tracker

Discord presence tracking plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — REST polling via [Lanyard](https://lanyard.dev), daily JSONL logs, and a `discord_activity` tool for querying presence data.

## Features

- **Auto-starts with Hermes** — daemon thread, no manual process management
- **REST polling** via Lanyard API (minute-aligned, 60s intervals)
- **Daily JSONL logs** — one file per day, constant-time queries regardless of history depth
- **`discord_activity` tool** — the agent can query presence data directly (status, timeline, stats, Spotify, history)
- **Cross-platform** — auto-detects system timezone, works on Windows, macOS, and Linux

## Configuration

Add these to your `.env` file (in your Hermes profile directory):

```env
# Required: Discord user ID to track
DISCORD_ACTIVITY_USER_ID=000000000000000000

# Optional: seconds between REST polls (default: 60)
DISCORD_ACTIVITY_POLL_INTERVAL=60

# Optional: Lanyard API base URL (default: https://api.lanyard.rest/v1)
DISCORD_ACTIVITY_LANYARD_API=https://api.lanyard.rest/v1
```

## Installation

1. Copy `hermes-discord-activity-tracker/` into your Hermes plugins directory:
   ```
   ~/.hermes/plugins/hermes-discord-activity-tracker/
   ```
   Or for a specific profile:
   ```
   ~/.hermes/profiles/<profile>/plugins/hermes-discord-activity-tracker/
   ```

2. Add `hermes-discord-activity-tracker` to `plugins.enabled` in your `config.yaml`

3. Set `DISCORD_ACTIVITY_USER_ID` in your `.env`

4. Restart Hermes

## Tool

The `discord_activity` tool is available to the agent once the plugin loads.

### Queries

| Query | Description | Parameters |
|-------|-------------|------------|
| `status` | Current Discord presence | — |
| `sessions` | App sessions with details aggregated | `days` (default: 1) |
| `stats` | Aggregated statistics | `days` (default: 1) |
| `spotify` | Recent Spotify listening | `minutes` (default: 60) or `days` |
| `history` | Raw recent entries | `minutes` (default: 60) |

### Example

```
discord_activity(query="stats", days=1)
```

```json
{
  "period_days": 1,
  "total_entries": 140,
  "elapsed_minutes": 32.6,
  "status_minutes": {"online": 32.6},
  "spotify": {
    "listening_minutes": 23.6,
    "unique_tracks": 7,
    "top_songs": [
      {"song": "Jason", "artist": "The Midnight; Nikki Flores", "minutes": 5.5}
    ]
  }
}
```

## Output

Daily JSONL files are written to:
```
~/.hermes/profiles/<profile>/logs/discord-activity/YYYY-MM-DD.jsonl
```

Each entry contains:
```json
{
  "timestamp": "2026-06-11T02:00:00.001275+07:00",
  "discord_status": "online",
  "activities": [],
  "spotify": {"song": "...", "artist": "...", "album": "..."},
  "platforms": {"desktop": true, "mobile": false, "web": false},
  "listening_to_spotify": false
}
```

## Architecture

```
hermes-discord-activity-tracker/
├── plugin.yaml        # Manifest (name, version, env requirements)
├── __init__.py        # Plugin registration + poller startup
├── poller.py          # REST polling daemon thread (Lanyard API)
├── schemas.py         # discord_activity tool schema
├── tools.py           # Query handler (reads JSONL → JSON responses)
└── LICENSE            # MIT
```

- **Poller** runs as a daemon thread inside the Hermes process — starts on load, dies with Hermes
- **PID lock** prevents duplicate pollers when multiple gateway instances run (e.g. Aura + Aria)
- **Tool** reads JSONL files on-demand and returns structured data to the agent
- **Tool** is self-describing (schema documents all queries) — no skills needed

## License

MIT
