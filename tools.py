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
    """
    seen = set()
    result = []
    for act in entry.get("activities", []):
        if not isinstance(act, dict):
            continue
        name = act.get("name")
        if not name or name.lower() == "spotify":
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

        party = act.get("party")
        if party and party.get("size"):
            size = party["size"]
            if isinstance(size, list) and len(size) >= 2:
                activity["party"] = {"current": size[0], "max": size[1]}

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
    """Extract Spotify info from an entry."""
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

        # Clean up internal accumulator
        accum = current_period.pop("_accumulated_activities", {})
        if accum:
            current_period["activity_details"] = list(accum.values())
        else:
            current_period["activity_details"] = None

        # Format Spotify display from collected tracks
        tracks = current_period.pop("_spotify_tracks", [])
        if tracks:
            if len(tracks) <= 3:
                current_period["spotify"] = " · ".join(
                    t.replace("|", " — ", 1) for t in tracks
                )
            else:
                unique_artists = []
                seen = set()
                for t in tracks:
                    artist = t.split("|", 1)[1]
                    if artist not in seen:
                        seen.add(artist)
                        unique_artists.append(artist)
                artists_str = ", ".join(unique_artists[:5])
                if len(unique_artists) > 5:
                    artists_str += f" +{len(unique_artists) - 5} more"
                current_period["spotify"] = f"{len(tracks)} tracks — {artists_str}"

        timeline.append(current_period)
        current_period = None

    def _make_period(entry, start_dt):
        names = _activity_names(entry)
        activity = ", ".join(names) if names else "Online"
        
        # Initialize internal accumulator dict for merging activities across this period
        accum = {}
        for act in _extract_activities(entry):
            accum[act["name"]] = act

        return {
            "_start_dt": start_dt,
            "_start_key": start_dt.strftime("%H:%M"),
            "start": start_dt.strftime("%H:%M"),
            "end": None,
            "duration": "0m",
            "duration_minutes": 0,
            "status": entry.get("discord_status") or "online",
            "activity": activity,
            "_accumulated_activities": accum,
            "spotify": None,
            "_spotify_tracks": [],  # Internal: collect all tracks
        }

    for e in entries:
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
                info = _extract_spotify(e)
                if info:
                    current_period["_spotify_tracks"].append(f"{info['song']}|{info['artist']}")
            prev_content = content
            continue

        if content != prev_content:
            _close_period(now)
            current_period = _make_period(e, now)

        # Accumulate/merge details during this period
        if current_period:
            new_acts = _extract_activities(e)
            accum = current_period["_accumulated_activities"]
            for act in new_acts:
                aname = act["name"]
                if aname in accum:
                    existing = accum[aname]
                    # Prioritize richer state (In Game over In Lobby)
                    is_new_richer = (
                        ("details" in act and "details" not in existing) or
                        ("timestamps" in act and "timestamps" not in existing) or
                        (act.get("state") == "In Game" and existing.get("state") != "In Game") or
                        (act.get("state") == "In Champion Select" and existing.get("state") == "In Lobby")
                    )

                    if is_new_richer:
                        # Retain existing fields if the new richer one doesn't have them
                        party = act.get("party") or existing.get("party")
                        champion = act.get("champion") or existing.get("champion")
                        large_text = act.get("large_text") or existing.get("large_text")

                        existing.update(act)
                        if party: existing["party"] = party
                        if champion: existing["champion"] = champion
                        if large_text: existing["large_text"] = large_text
                    else:
                        # Just merge any new fields into the richer existing one
                        if "party" not in existing and "party" in act:
                            existing["party"] = act["party"]
                        if "champion" not in existing and "champion" in act:
                            existing["champion"] = act["champion"]
                        if "large_text" not in existing and "large_text" in act:
                            existing["large_text"] = act["large_text"]
                        if "timestamps" not in existing and "timestamps" in act:
                            existing["timestamps"] = act["timestamps"]
                        if "details" not in existing and "details" in act:
                            existing["details"] = act["details"]
                else:
                    accum[aname] = act

        if has_spotify and current_period:
            info = _extract_spotify(e)
            if info:
                track_key = f"{info['song']}|{info['artist']}"
                if not current_period["_spotify_tracks"] or current_period["_spotify_tracks"][-1] != track_key:
                    current_period["_spotify_tracks"].append(track_key)

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
    content_counter = defaultdict(lambda: {"count": 0, "app": ""})  # "app|details" → count
    for i in range(len(entries) - 1):
        sec = (entries[i + 1]["_dt"] - entries[i]["_dt"]).total_seconds()
        if sec > 1800:
            continue
        acts = _extract_activities(entries[i])
        for act in acts:
            name = act["name"]
            activity_ms[name] += sec * 1000
            details = act.get("details")
            if details:
                ckey = f"{name}{_KEY_SEP}{details}"
                content_counter[ckey]["count"] += 1
                content_counter[ckey]["app"] = name

    top_activities = []
    for name, ms in sorted(activity_ms.items(), key=lambda x: -x[1])[:10]:
        top_activities.append({"name": name, "minutes": round(ms / 60000, 1)})

    top_content = []
    for ckey, info in sorted(content_counter.items(), key=lambda x: -x[1]["count"])[:10]:
        _, details = ckey.split(_KEY_SEP, 1)
        top_content.append({"app": info["app"], "details": details, "seen": info["count"]})

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
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        return json.dumps({"error": str(e)})
