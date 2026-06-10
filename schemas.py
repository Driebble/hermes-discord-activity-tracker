"""Tool schemas for the discord-activity plugin."""

DISCORD_ACTIVITY = {
    "name": "discord_activity",
    "description": "Query Discord presence data for the tracked user. Returns status, activity timeline, Spotify listening history, or aggregated statistics.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "enum": ["status", "timeline", "stats", "spotify", "history"],
                "description": (
                    "What to query: "
                    "'status' = current presence, "
                    "'timeline' = activity periods, "
                    "'stats' = aggregated stats, "
                    "'spotify' = recent listening, "
                    "'history' = raw entries"
                ),
            },
            "minutes": {
                "type": "integer",
                "description": "Time range in minutes for timeline/history/spotify queries (default: 60)",
            },
            "days": {
                "type": "integer",
                "description": "Time range in days for stats/timeline queries (default: 1)",
            },
        },
        "required": ["query"],
    },
}
