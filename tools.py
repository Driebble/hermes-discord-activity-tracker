"""Tool handlers for the discord-activity plugin.

Reads daily JSONL files and returns presence data to the LLM.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# ─── Hermes home detection (matches standard plugin pattern) ─────

try:
    from hermes_constants import get_hermes_home
except ImportError:
    def get_hermes_home() -> Path:
        val = (os.environ.get("HERMES_HOME") or "").strip()
        return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()

_LOG_SUBDIR = "logs/discord-activity"

# Runtime configuration — set by __init__.register() from env vars.
# Defaults match prior hardcoded behavior.
IGNORE_SPOTIFY = False
SESSION_GAP_MINUTES = 30

_ACTIVITY_TYPE_MAP = {
    0: "playing",
    1: "streaming",
    2: "listening",
    3: "watching",
    4: "custom",
    5: "competing",
}


def _get_log_dir():
    """Get the log directory, creating it if needed."""
    log_dir = get_hermes_home() / _LOG_SUBDIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# ─── Data Loading ────────────────────────────────────────────────


def _load_entries(log_dir, cutoff):
    """Load entries from daily JSONL files within the time window."""
    entries = []
    cutoff_date = cutoff.strftime("%Y-%m-%d")

    if log_dir.is_dir():
        for filename in sorted(os.listdir(log_dir)):
            if not filename.endswith(".jsonl"):
                continue
            file_date = filename.removesuffix(".jsonl")
            if file_date < cutoff_date:
                continue
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


# ─── Helpers ─────────────────────────────────────────────────────


def _activity_names(entry):
    """Get unique non-Spotify activity names."""
    names = []
    seen = set()
    for act in entry.get("activities", []):
        if isinstance(act, dict):
            name = act.get("name")
            if name and name.lower() != "spotify" and name not in seen:
                names.append(name)
                seen.add(name)
    return names


def _extract_activities(entry):
    """Extract rich activity data for all non-Spotify activities.

    Returns a list of activity dicts with key fields from Discord's
    Rich Presence format. Handles any app generically.
    Deduplicates by (name, details, state) — same video from multiple
    sources (PreMiD + native) collapses to one.
    Only extracts games when they are actively "In Game".

    When IGNORE_SPOTIFY is set, the dedicated Spotify activity entry
    (PreMiD-style "Spotify" presence) is filtered from the activity list.
    The structured spotify block is filtered separately in _extract_spotify.
    """
    seen = set()
    result = []
    for act in entry.get("activities", []):
        if not isinstance(act, dict):
            continue
        name = act.get("name")
        if not name or name.lower() == "spotify":
            continue

        # League of Legends special-case: filter menu/lobby/queue time.
        # The LoL client doesn't always populate the `state` field, so we
        # use `details` (e.g. "ARAM: Mayhem") as the "in a match" signal.
        # Other games are not affected — they typically only emit rich
        # presence while actively playing, so menu filtering isn't needed.
        if act.get("name") == "League of Legends" and not act.get("details"):
            continue

        details = act.get("details")
        state = act.get("state")

        # Deduplicate by (name, details, state)
        sig = (name, details, state)
        if sig in seen:
            continue
        seen.add(sig)

        activity = {
            "name": name,
            "type": _ACTIVITY_TYPE_MAP.get(act.get("type"), "unknown"),
        }

        if details:
            activity["details"] = details

        if state:
            activity["state"] = state

        timestamps = act.get("timestamps")
        if timestamps:
            ts_data = {}
            if timestamps.get("start"):
                ts_data["start"] = timestamps["start"]
            if timestamps.get("end"):
                ts_data["end"] = timestamps["end"]
            if ts_data:
                activity["timestamps"] = ts_data

        # Generic assets helper (large_text / small_text / champion name)
        assets = act.get("assets")
        if assets:
            if assets.get("large_text"):
                activity["large_text"] = assets["large_text"]
                if name == "League of Legends":
                    activity["champion"] = assets["large_text"]

        result.append(activity)

    return result


def _extract_spotify(entry):
    """Extract Spotify info from an entry. Returns None when IGNORE_SPOTIFY is set."""
    if IGNORE_SPOTIFY:
        return None
    spotify = entry.get("spotify")
    if not spotify:
        return None
    song = spotify.get("song")
    artist = spotify.get("artist")
    if not song:
        return None
    return {"song": song, "artist": artist or "Unknown"}


# Safe separator for composite keys (song|artist can contain |)
_KEY_SEP = "\x00"


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
                        activities = _extract_activities(entry)
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


def _get_sessions(log_dir, days):
    """Build session-based aggregations grouped by app."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = _load_entries(log_dir, cutoff)

    if not entries:
        return json.dumps({"apps": {}})

    # app_name -> list of session dicts
    app_sessions = defaultdict(list)
    
    # Gap threshold to split sessions (minutes, configurable via env)
    GAP_THRESHOLD_MINUTES = SESSION_GAP_MINUTES

    for e in entries:
        now = e["_dt"]
        for act in _extract_activities(e):
            app_name = act["name"]
            sessions = app_sessions[app_name]
            
            # Should we create a new session or append to the last one?
            if not sessions:
                make_new = True
            else:
                last_sess = sessions[-1]
                gap = (now - last_sess["_last_seen"]).total_seconds() / 60.0
                make_new = gap > GAP_THRESHOLD_MINUTES
                
            if make_new:
                sessions.append({
                    "_start_dt": now,
                    "_last_seen": now,
                    "start": now.strftime("%H:%M"),
                    "end": now.strftime("%H:%M"),
                    "duration_minutes": 0,
                    "details": set()
                })
            
            sess = sessions[-1]
            sess["_last_seen"] = now
            sess["end"] = now.strftime("%H:%M")
            sess["duration_minutes"] = round((now - sess["_start_dt"]).total_seconds() / 60.0)
            
            # Extract detail strings (e.g. video titles, champions, file names)
            detail_str = act.get("champion") or act.get("details")
            if detail_str and detail_str not in ("Idling", "Searching for", "Viewing Homepage", "Browsing repository"):
                # Clean up known prefixes for brevity
                if detail_str.startswith("Working on "):
                    detail_str = detail_str.split(":")[0]  # Remove line numbers
                sess["details"].add(detail_str)

    # Format the final output
    result = {}
    for app_name, sessions in app_sessions.items():
        formatted_sessions = []
        total_mins = 0
        for s in sessions:
            if s["duration_minutes"] < 1:
                continue  # Skip transient blips
            dur = s["duration_minutes"]
            total_mins += dur
            dur_str = f"{dur}m" if dur < 60 else f"{dur/60:.1f}h"
            formatted_sessions.append({
                "start": s["start"],
                "end": s["end"],
                "duration": dur_str,
                "details": list(s["details"])
            })
        
        if formatted_sessions:
            total_str = f"{total_mins}m" if total_mins < 60 else f"{total_mins/60:.1f}h"
            result[app_name] = {
                "total_duration": total_str,
                "sessions": formatted_sessions
            }

    return json.dumps({"apps": result})


def _get_stats(log_dir, days):
    """Get aggregated statistics."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = _load_entries(log_dir, cutoff)

    if not entries:
        return json.dumps({"error": "No entries found"})

    # Shared gap threshold — same value the sessions query uses.
    # Configurable via DISCORD_ACTIVITY_SESSION_GAP_MINUTES.
    gap_seconds = SESSION_GAP_MINUTES * 60

    # Status minutes
    status_minutes = defaultdict(float)
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec <= gap_seconds:
            status = entries[i].get("discord_status") or "online"
            status_minutes[status] += sec / 60.0

    # Platform minutes
    platform_minutes = {"desktop": 0.0, "mobile": 0.0, "web": 0.0}
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec <= gap_seconds:
            platforms = entries[i].get("platforms", {})
            active = [p for p in ("desktop", "mobile", "web") if platforms.get(p)]
            if active:
                share = sec / 60.0 / len(active)
                for p in active:
                    platform_minutes[p] += share

    # Spotify stats — each track play has a unique timestamps.start
    # Skipped when IGNORE_SPOTIFY is set; the response "spotify" key
    # returns zeros so the schema stays stable for callers.
    seen_plays = set()
    track_ms = defaultdict(float)
    artist_ms = defaultdict(float)
    if not IGNORE_SPOTIFY:
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
                key = f"{song}{_KEY_SEP}{artist}"
                track_ms[key] += dur_ms
                for a in artist.split(";"):
                    a = a.strip()
                    if a:
                        artist_ms[a] += dur_ms

    top_songs = []
    for key, ms in sorted(track_ms.items(), key=lambda x: -x[1])[:10]:
        song, artist = key.split(_KEY_SEP, 1)
        top_songs.append({"song": song, "artist": artist, "minutes": round(ms / 60000, 1)})

    top_artists = []
    for artist, ms in sorted(artist_ms.items(), key=lambda x: -x[1])[:10]:
        top_artists.append({"artist": artist, "minutes": round(ms / 60000, 1)})

    # Non-Spotify activity stats — track by app name + details/content
    activity_ms = defaultdict(float)  # app name → total ms
    content_counter = defaultdict(lambda: {"ms": 0.0, "app": ""})  # "app|details" → ms
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec > gap_seconds:
            continue
        acts = _extract_activities(entries[i])
        for act in acts:
            name = act["name"]
            activity_ms[name] += sec * 1000
            details = act.get("details")
            if details:
                ckey = f"{name}{_KEY_SEP}{details}"
                content_counter[ckey]["ms"] += sec * 1000
                content_counter[ckey]["app"] = name

    top_activities = []
    for name, ms in sorted(activity_ms.items(), key=lambda x: -x[1])[:10]:
        top_activities.append({"name": name, "minutes": round(ms / 60000, 1)})

    top_content = []
    for ckey, info in sorted(content_counter.items(), key=lambda x: -x[1]["ms"])[:10]:
        _, details = ckey.split(_KEY_SEP, 1)
        top_content.append({"app": info["app"], "details": details, "minutes": round(info["ms"] / 60000, 1)})

    # Total elapsed
    elapsed = (entries[-1]["_dt"] - entries[0]["_dt"]).total_seconds() / 60 if len(entries) >= 2 else 0

    return json.dumps({
        "period_days": days,
        "total_entries": len(entries),
        "elapsed_minutes": round(elapsed, 1),
        "status_minutes": {k: round(v, 1) for k, v in sorted(status_minutes.items(), key=lambda x: -x[1])},
        "platform_minutes": {k: round(v, 1) for k, v in platform_minutes.items()},
        "activities": {
            "top_apps": top_activities,
            "top_content": top_content,
        },
        "spotify": {
            "listening_minutes": round(sum(track_ms.values()) / 60000, 1),
            "unique_tracks": len(track_ms),
            "unique_artists": len(artist_ms),
            "top_songs": top_songs,
            "top_artists": top_artists,
        },
    })


def _get_spotify(log_dir, minutes=None, days=None):
    """Get recent Spotify listening history. Returns empty when IGNORE_SPOTIFY is set."""
    if IGNORE_SPOTIFY:
        return json.dumps({"songs": [], "total_entries": 0, "ignored": True})
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes or 60)
        
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
            "activities": _extract_activities(e),
            "spotify": _extract_spotify(e),
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
        elif query == "sessions":
            return _get_sessions(log_dir, days)
        elif query == "stats":
            return _get_stats(log_dir, days)
        elif query == "spotify":
            return _get_spotify(log_dir, minutes=args.get("minutes"), days=args.get("days"))
        elif query == "history":
            return _get_history(log_dir, minutes)
        else:
            return json.dumps({"error": f"Unknown query: {query}"})
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        return json.dumps({"error": str(e)})
