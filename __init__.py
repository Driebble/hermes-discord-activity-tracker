"""Discord Activity Plugin — REST presence tracking via Lanyard.

Auto-starts a background poller thread when Hermes loads this plugin.
Exposes a discord_activity tool for querying presence data.
"""

import os
from pathlib import Path


def _get_log_dir():
    """Resolve log directory using hermes_constants (standard plugin pattern)."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        def get_hermes_home() -> Path:
            val = (os.environ.get("HERMES_HOME") or "").strip()
            return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()
    return get_hermes_home() / "logs" / "discord-activity"


def register(ctx):
    """Register the discord_activity tool and start the background poller."""
    user_id = os.environ.get("DISCORD_ACTIVITY_USER_ID")
    if not user_id:
        print("[discord-activity] DISCORD_ACTIVITY_USER_ID not set — plugin disabled")
        return

    api_base = os.environ.get("DISCORD_ACTIVITY_LANYARD_API", "https://api.lanyard.rest/v1")
    try:
        poll_interval = int(os.environ.get("DISCORD_ACTIVITY_POLL_INTERVAL", "60"))
    except ValueError:
        print("[discord-activity] Invalid DISCORD_ACTIVITY_POLL_INTERVAL, using default 60s")
        poll_interval = 60
    api_url = f"{api_base}/users/{user_id}"

    log_dir = _get_log_dir()

    # Register tool
    from . import schemas, tools

    ctx.register_tool(
        name="discord_activity",
        toolset="hermes-discord-activity-tracker",
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
