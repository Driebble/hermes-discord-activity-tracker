"""Tool schemas for the discord-activity plugin."""

DISCORD_ACTIVITY = {
    "name": "discord_activity",
    "description": "Query Discord presence data for the tracked user. Returns status, activity timeline, Spotify listening history, or aggregated statistics.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "enum": ["status", "sessions", "stats", "spotify", "history"],
                "description": "What to query: 'status' = current presence, 'sessions' = continuous app sessions, 'stats' = aggregated stats, 'spotify' = recent listening, 'history' = raw entries"
            },
            "days": {
                "type": "integer",
                "description": "Time range in days for stats/sessions queries (default: 1)",
            },
            "minutes": {
                "type": "integer",
                "description": "Time range in minutes for history/spotify queries (default: 60)",
            },
        },
        "required": ["query"],
    },
}
