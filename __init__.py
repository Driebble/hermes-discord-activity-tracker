"""Discord Activity Plugin — REST presence tracking via Lanyard.

Auto-starts a background poller thread when Hermes loads this plugin.
Exposes a discord_activity tool for querying presence data.
"""

import os
from pathlib import Path


def register(ctx):
    """Register the discord_activity tool and start the background poller."""
    # Load config from environment
    user_id = os.environ.get("DISCORD_ACTIVITY_USER_ID")
    if not user_id:
        print("[discord-activity] DISCORD_ACTIVITY_USER_ID not set — plugin disabled")
        return

    api_base = os.environ.get("DISCORD_ACTIVITY_LANYARD_API", "https://api.lanyard.rest/v1")
    poll_interval = int(os.environ.get("DISCORD_ACTIVITY_POLL_INTERVAL", "60"))
    api_url = f"{api_base}/users/{user_id}"

    log_dir = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes" / "profiles" / "aura")) / "logs" / "discord-activity"

    # Register tool
    from . import schemas, tools

    ctx.register_tool(
        name="discord_activity",
        toolset="discord-activity",
        schema=schemas.DISCORD_ACTIVITY,
        handler=tools.discord_activity,
    )

    # Start background poller
    from .poller import ActivityPoller

    poller = ActivityPoller(
        user_id=user_id,
        api_url=api_url,
        poll_interval=poll_interval,
        log_dir=log_dir,
    )
    poller.start()

    # Register cleanup
    import atexit
    atexit.register(poller.stop)
