"""Discord Activity Plugin — REST presence tracking via Lanyard.

Auto-starts a background poller thread when Hermes loads this plugin.
CLI commands that load plugins will trigger the poller, but the PID lock
ensures only one poller runs per log directory. The poller is a daemon
thread — it dies cleanly when the process exits.
Exposes a discord_activity tool for querying presence data.
"""

import os
import sys
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


def _truthy(value):
    """Parse a string env var as boolean. Defaults to False on empty/invalid."""
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_gap(value, default=30):
    """Parse a session-gap env var as positive int, falling back to default."""
    try:
        n = int((value or "").strip())
        return n if n > 0 else default
    except (ValueError, AttributeError):
        return default


def register(ctx):
    """Register the discord_activity tool and start the background poller."""
    user_id = os.environ.get("DISCORD_ACTIVITY_USER_ID")
    if not user_id:
        return

    # Read optional env config (with safe defaults)
    ignore_spotify = _truthy(os.environ.get("DISCORD_ACTIVITY_IGNORE_SPOTIFY"))
    session_gap_minutes = _parse_gap(os.environ.get("DISCORD_ACTIVITY_SESSION_GAP_MINUTES"))

    # Register tool
    from . import schemas, tools as discord_tools

    ctx.register_tool(
        name="discord_activity",
        toolset="hermes-discord-activity-tracker",
        schema=schemas.DISCORD_ACTIVITY,
        handler=discord_tools.discord_activity,
    )

    # Make the runtime config visible to the query handlers
    discord_tools.IGNORE_SPOTIFY = ignore_spotify
    discord_tools.SESSION_GAP_MINUTES = session_gap_minutes

    # Start poller — PID lock prevents duplicates if CLI and gateway coexist.
    # The poller is a daemon thread: it dies when the process exits.
    api_base = os.environ.get("DISCORD_ACTIVITY_LANYARD_API", "https://api.lanyard.rest/v1")
    try:
        poll_interval = int(os.environ.get("DISCORD_ACTIVITY_POLL_INTERVAL", "60"))
    except ValueError:
        poll_interval = 60

    from .poller import ActivityPoller

    poller = ActivityPoller(
        user_id=user_id,
        api_url=f"{api_base}/users/{user_id}",
        poll_interval=poll_interval,
        log_dir=_get_log_dir(),
    )
    try:
        poller.start()
    except Exception as e:
        print(f"[discord-activity] Poller failed to start: {e}", file=sys.stderr)
        return

    import atexit
    atexit.register(poller.stop)
