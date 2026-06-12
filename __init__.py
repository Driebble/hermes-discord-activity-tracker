"""Discord Activity Plugin — REST presence tracking via Lanyard.

Exposes a discord_activity tool for querying presence data.
Poller starts lazily on first tool call (not during register).
CLI commands like `hermes model` won't trigger poller start/stop.
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


# Module-level state for lazy poller init
_poller = None
_poller_started = False
_config = {}


def _ensure_poller():
    """Start the poller on first call (lazy init)."""
    global _poller, _poller_started
    if _poller_started:
        return
    _poller_started = True

    from .poller import ActivityPoller

    _poller = ActivityPoller(
        user_id=_config["user_id"],
        api_url=_config["api_url"],
        poll_interval=_config["poll_interval"],
        log_dir=_config["log_dir"],
    )
    _poller.start()

    import atexit
    atexit.register(_poller.stop)


def _tool_handler(args, **kwargs):
    """Tool wrapper that ensures poller is running before handling queries."""
    _ensure_poller()
    from . import tools
    return tools.discord_activity(args, **kwargs)


def register(ctx):
    """Register the discord_activity tool. Configures but does NOT start poller."""
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

    _config.update({
        "user_id": user_id,
        "api_url": f"{api_base}/users/{user_id}",
        "poll_interval": poll_interval,
        "log_dir": _get_log_dir(),
    })

    # Register tool with wrapper handler (poller starts on first call)
    from . import schemas

    ctx.register_tool(
        name="discord_activity",
        toolset="hermes-discord-activity-tracker",
        schema=schemas.DISCORD_ACTIVITY,
        handler=_tool_handler,
    )
