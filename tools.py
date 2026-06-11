"""Tool handlers for the discord-activity plugin.

Reads daily JSONL files and returns presence data to the LLM.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# Default paths
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes" / "profiles" / "aura"))
_DEFAULT_LOG_DIR = _HERMES_HOME / "logs" / "discord-activity"


def _get_log_dir():
    """Get the log directory, creating it if needed."""
    log_dir = _DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _load_entries(log_dir, cutoff):
    """Load entries from daily JSONL files within the time window."""
    entries = []

    if log_dir.is_dir():
        for filename in sorted(os.listdir(log_dir)):
            if filename.endswith(".jsonl"):
                _load_file(entries, log_dir / filename, cutoff)

    entries.sort(key=lambda e: e["_dt"])
    return entries


def _load_file(entries, filepath, cutoff):
    """Load entries from a single JSONL file."""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = entry.get("timestamp")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
                if ts >= cutoff:
                    entry["_dt"] = ts
                    entries.append(entry)
            except ValueError:
                continue


def _activity_names(entry):
    """Get non-Spotify activity names."""
    names = []
    for act in entry.get("activities", []):
        if isinstance(act, dict):
            name = act.get("name")
            if name and name.lower() != "spotify":
                names.append(name)
    return names


def _extract_spotify(entry):
    """Extract Spotify info from an entry."""
    spotify = entry.get("spotify")
    if not spotify:
        return None
    song = spotify.get("song")
    artist = spotify.get("artist")
    if not song:
        return None
    return {"song": song, "artist": artist or "Unknown"}


def _format_spotify(entry):
    """Format Spotify info as a display string."""
    info = _extract_spotify(entry)
    if not info:
        return None
    return f"{info['song']} — {info['artist']}"


# ─── Query Handlers ──────────────────────────────────────────────


def _get_current_status(log_dir):
    """Get the most recent presence entry — fast, reads only the last line."""
    log_files = []
    if log_dir.is_dir():
        log_files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(".jsonl")],
            reverse=True,
        )

    for filename in log_files:
        filepath = log_dir / filename
        try:
            with open(filepath, "rb") as f:
                f.seek(0, 2)  # Seek to end
                size = f.tell()
                if size == 0:
                    continue
                # Read last 4KB or the whole file if smaller
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", errors="replace")
                # Get the last non-empty line
                for line in reversed(tail.splitlines()):
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        entry["_dt"] = datetime.fromisoformat(entry["timestamp"])
                        activities = _activity_names(entry)
                        spotify = _extract_spotify(entry)
                        return json.dumps({
                            "status": entry.get("discord_status"),
                            "activities": activities,
                            "spotify": spotify,
                            "platforms": entry.get("platforms", {}),
                            "last_updated": entry.get("timestamp"),
                        })
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    return json.dumps({"error": "No presence data found"})


def _get_timeline(log_dir, days):
    """Build activity timeline by comparing consecutive entries."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = _load_entries(log_dir, cutoff)

    if not entries:
        return json.dumps({"timeline": [], "message": "No entries found"})

    timeline = []
    current_period = None
    prev_content = None

    def _close_period(end_dt):
        nonlocal current_period
        if current_period is None:
            return
        current_period["end"] = end_dt.strftime("%H:%M")
        dur = (end_dt - current_period["_start_dt"]).total_seconds() / 60.0
        current_period["duration"] = f"{dur:.0f}m" if dur < 60 else f"{dur/60:.1f}h"
        current_period["duration_minutes"] = round(dur, 1)
        del current_period["_start_dt"]
        del current_period["_start_key"]
        timeline.append(current_period)
        current_period = None

    def _make_period(entry, start_dt):
        names = _activity_names(entry)
        activity = ", ".join(names) if names else "Online"
        return {
            "_start_dt": start_dt,
            "_start_key": start_dt.strftime("%H:%M"),
            "start": start_dt.strftime("%H:%M"),
            "end": None,
            "duration": "0m",
            "duration_minutes": 0,
            "status": entry.get("discord_status") or "online",
            "activity": activity,
            "spotify": None,
        }

    for e in entries:
        # Content = activities + spotify state (not specific track)
        names = _activity_names(e)
        has_spotify = bool((e.get("spotify") or {}).get("song"))
        content = (
            tuple(sorted(names)),
            has_spotify,
        )
        now = e["_dt"]

        if prev_content is None:
            current_period = _make_period(e, now)
            if has_spotify:
                current_period["spotify"] = _format_spotify(e)
            prev_content = content
            continue

        if content != prev_content:
            _close_period(now)
            current_period = _make_period(e, now)

        # Update Spotify display to latest track in this period
        if has_spotify and current_period:
            current_period["spotify"] = _format_spotify(e)

        prev_content = content

    if entries:
        _close_period(entries[-1]["_dt"])

    # Filter out periods shorter than 1 minute
    timeline = [p for p in timeline if p["duration_minutes"] >= 1.0]

    # Filter out "Online (no activity)" periods — keep only real activity
    timeline = [p for p in timeline if p["activity"] != "Online" or p.get("spotify")]

    return json.dumps({"timeline": timeline, "periods": len(timeline)})


def _get_stats(log_dir, days):
    """Get aggregated statistics."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = _load_entries(log_dir, cutoff)

    if not entries:
        return json.dumps({"error": "No entries found"})

    # Status minutes
    status_minutes = defaultdict(float)
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec <= 1800:  # < 30 min gap
            status = entries[i].get("discord_status") or "online"
            status_minutes[status] += sec / 60.0

    # Platform minutes
    platform_minutes = {"desktop": 0.0, "mobile": 0.0, "web": 0.0}
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec <= 1800:
            platforms = entries[i].get("platforms", {})
            active = [p for p in ("desktop", "mobile", "web") if platforms.get(p)]
            if active:
                share = sec / 60.0 / len(active)
                for p in active:
                    platform_minutes[p] += share

    # Spotify stats — each track play has a unique timestamps.start
    seen_plays = set()
    track_ms = defaultdict(float)
    artist_ms = defaultdict(float)
    for e in entries:
        spotify = e.get("spotify")
        if not spotify:
            continue
        song = spotify.get("song")
        artist = spotify.get("artist") or "Unknown"
        if not song:
            continue
        ts_info = spotify.get("timestamps", {})
        play_start = ts_info.get("start")
        end_ms = ts_info.get("end")
        if play_start and end_ms and play_start not in seen_plays:
            seen_plays.add(play_start)
            dur_ms = max(0, end_ms - play_start)
            key = f"{song}|{artist}"
            track_ms[key] += dur_ms
            for a in artist.split(";"):
                a = a.strip()
                if a:
                    artist_ms[a] += dur_ms

    top_songs = []
    for key, ms in sorted(track_ms.items(), key=lambda x: -x[1])[:10]:
        song, artist = key.split("|", 1)
        top_songs.append({"song": song, "artist": artist, "minutes": round(ms / 60000, 1)})

    top_artists = []
    for artist, ms in sorted(artist_ms.items(), key=lambda x: -x[1])[:10]:
        top_artists.append({"artist": artist, "minutes": round(ms / 60000, 1)})

    # Total elapsed
    elapsed = (entries[-1]["_dt"] - entries[0]["_dt"]).total_seconds() / 60 if len(entries) >= 2 else 0

    return json.dumps({
        "period_days": days,
        "total_entries": len(entries),
        "elapsed_minutes": round(elapsed, 1),
        "status_minutes": {k: round(v, 1) for k, v in sorted(status_minutes.items(), key=lambda x: -x[1])},
        "platform_minutes": {k: round(v, 1) for k, v in platform_minutes.items()},
        "spotify": {
            "listening_minutes": round(sum(track_ms.values()) / 60000, 1),
            "unique_tracks": len(track_ms),
            "unique_artists": len(artist_ms),
            "top_songs": top_songs,
            "top_artists": top_artists,
        },
    })


def _get_spotify(log_dir, minutes):
    """Get recent Spotify listening history."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    entries = _load_entries(log_dir, cutoff)

    songs = []
    for e in entries:
        spotify = e.get("spotify")
        if spotify and spotify.get("song"):
            ts_str = e.get("timestamp", "")[:19]
            songs.append({
                "time": ts_str,
                "song": spotify["song"],
                "artist": spotify.get("artist", "Unknown"),
            })

    # Deduplicate consecutive same-song entries
    deduped = []
    for s in songs:
        if not deduped or s["song"] != deduped[-1]["song"]:
            deduped.append(s)

    return json.dumps({"songs": deduped, "total_entries": len(deduped)})


def _get_history(log_dir, minutes):
    """Get raw recent entries."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    entries = _load_entries(log_dir, cutoff)

    result = []
    for e in entries[-20:]:  # Last 20 entries max
        result.append({
            "time": e.get("timestamp", "")[:19],
            "status": e.get("discord_status"),
            "activities": _activity_names(e),
            "spotify": (e.get("spotify") or {}).get("song"),
        })

    return json.dumps({"entries": result, "total": len(entries)})


# ─── Tool Entry Point ────────────────────────────────────────────


def discord_activity(args: dict, **kwargs) -> str:
    """Handle discord_activity tool calls."""
    query = args.get("query", "status")
    minutes = args.get("minutes", 60)
    days = args.get("days", 1)

    log_dir = _get_log_dir()

    try:
        if query == "status":
            return _get_current_status(log_dir)
        elif query == "timeline":
            return _get_timeline(log_dir, days)
        elif query == "stats":
            return _get_stats(log_dir, days)
        elif query == "spotify":
            return _get_spotify(log_dir, minutes)
        elif query == "history":
            return _get_history(log_dir, minutes)
        else:
            return json.dumps({"error": f"Unknown query: {query}"})
    except Exception as e:
        return json.dumps({"error": str(e)})
