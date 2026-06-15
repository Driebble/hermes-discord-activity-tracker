# hermes-discord-activity-tracker

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that tracks Discord presence via [Lanyard](https://github.com/phineas/lanyard) REST polling, with daily JSONL logs and a `discord_activity` tool for querying presence data.

## Features

- **Auto-starts with Hermes** — daemon thread, no manual process management
- **REST polling** via Lanyard API (minute-aligned, configurable intervals)
- **Daily JSONL logs** — one file per day, constant-time queries regardless of history depth
- **`discord_activity` tool** — the agent can query presence data directly (status, sessions, stats, Spotify, history)
- **Cross-platform** — auto-detects system timezone, works on Windows, macOS, and Linux

## Installation

This plugin uses [Lanyard](https://github.com/phineas/lanyard) to track your Discord presence. Lanyard exposes a REST API that this plugin polls. You have two options:

- **Join the official Lanyard Discord server** (https://discord.gg/UrXF2cfJ7F) — join it to get your own API endpoint, then set `DISCORD_ACTIVITY_LANYARD_API` to your personal endpoint
- **Self-host Lanyard** — see the [Lanyard GitHub repo](https://github.com/phineas/lanyard) for setup instructions, then point `DISCORD_ACTIVITY_LANYARD_API` to your own server

1. Clone the plugin into your Hermes plugins directory:
   ```bash
   git clone https://github.com/Driebble/hermes-discord-activity-tracker.git ~/.hermes/plugins/hermes-discord-activity-tracker
   ```
2. Enable this plugin by adding it to your `config.yaml`:
   ```yaml
   plugins:
     enabled:
       - hermes-discord-activity-tracker
   ```
3. Set your Discord user ID in your profile's `.env` file (see Configuration below).
4. Restart your Hermes gateway process.

## Configuration

Add these to your profile's `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_ACTIVITY_USER_ID` | *required* | Your Discord user ID (right-click your name → Copy User ID) |
| `DISCORD_ACTIVITY_POLL_INTERVAL` | `60` | Seconds between REST polls |
| `DISCORD_ACTIVITY_LANYARD_API` | `https://api.lanyard.rest/v1` | Lanyard API base URL. Point this to your own self-hosted Lanyard server if you're not using the official Discord bot |

```env
DISCORD_ACTIVITY_USER_ID=000000000000000000
```

## Usage

The `discord_activity` tool is available to the agent once the plugin loads.

| Query | Description | Parameters |
|-------|-------------|------------|
| `status` | Current Discord presence | — |
| `sessions` | App sessions with details aggregated | `days` (default: 1) |
| `stats` | Aggregated statistics | `days` (default: 1) |
| `spotify` | Recent Spotify listening | `minutes` (default: 60) or `days` |
| `history` | Raw recent entries | `minutes` (default: 60) |

```json
discord_activity(query="stats", days=1)
```

## File Structure

Daily JSONL files are written to:
```
~/.hermes/profiles/<profile>/logs/discord-activity/YYYY-MM-DD.jsonl
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
- **PID lock** prevents duplicate pollers when multiple gateway instances run
- **Tool** reads JSONL files on-demand and returns structured data to the agent

## License

MIT
