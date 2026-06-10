"""Discord Activity Poller — REST polling via Lanyard.

Runs as a daemon thread inside the Hermes process.
Writes presence snapshots to daily JSONL files.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error

    class _RequestsFallback:
        """Minimal requests-like wrapper using urllib."""

        def get(self, url, timeout=10):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    return _Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return _Response(b"", e.code)

    class _Response:
        def __init__(self, data, status_code):
            self._data = data
            self.status_code = status_code

        def json(self):
            return json.loads(self._data)

    requests = _RequestsFallback()


WIB = timezone(timedelta(hours=7))


class ActivityPoller:
    """Background thread that polls Lanyard REST and writes daily JSONL."""

    def __init__(self, user_id, api_url, poll_interval, log_dir):
        self.user_id = user_id
        self.api_url = api_url
        self.poll_interval = poll_interval
        self.log_dir = Path(log_dir)
        self._stop = threading.Event()
        self._thread = None
        self._poll_count = 0
        self._error_count = 0

    def start(self):
        """Start the polling thread (only if not already running)."""
        # PID lock to prevent duplicate pollers across gateway instances
        lock_file = self.log_dir / ".poller.lock"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        if lock_file.exists():
            try:
                old_pid = int(lock_file.read_text().strip())
                # Check if that process is still alive
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x100000, False, old_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    print("[discord-activity] Poller already running (another instance holds lock)")
                    return
            except (ValueError, OSError):
                pass

        lock_file.write_text(str(os.getpid()))
        self._lock_file = lock_file

        self._thread = threading.Thread(target=self._run, daemon=True, name="discord-activity-poller")
        self._thread.start()
        print(f"[discord-activity] Poller started → {self.log_dir}/YYYY-MM-DD.jsonl")

    def stop(self):
        """Signal the polling thread to stop and wait for it."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        # Release lock file
        if hasattr(self, "_lock_file") and self._lock_file and self._lock_file.exists():
            try:
                self._lock_file.unlink()
            except OSError:
                pass
        print(f"[discord-activity] Poller stopped (polls: {self._poll_count}, errors: {self._error_count})")

    def _run(self):
        """Main polling loop — runs in a background thread."""
        while not self._stop.is_set():
            # Sleep until the next minute boundary for aligned ticks
            now = datetime.now(WIB)
            wait = 60 - now.second - now.microsecond / 1_000_000
            if wait > 0:
                self._stop.wait(wait)
            if self._stop.is_set():
                break

            now = datetime.now(WIB)
            data = self._fetch()

            if data and data.get("discord_status") is not None:
                entry = self._make_entry(data, now)
                self._write(entry)
                self._poll_count += 1
            else:
                self._error_count += 1
                if self._error_count <= 3:
                    print(f"[discord-activity] [{now.strftime('%H:%M:%S')}] Skipped (no data)")

    def _fetch(self):
        """Fetch current presence from Lanyard REST API."""
        try:
            resp = requests.get(self.api_url, timeout=10)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success"):
                    return body.get("data")
        except Exception as e:
            if self._error_count <= 3:
                print(f"[discord-activity] Fetch error: {e}")
        return None

    def _make_entry(self, data, now):
        """Convert Lanyard presence data to a JSONL entry."""
        return {
            "timestamp": now.isoformat(),
            "discord_status": data.get("discord_status"),
            "activities": data.get("activities", []),
            "spotify": data.get("spotify"),
            "platforms": {
                "desktop": data.get("active_on_discord_desktop", False),
                "mobile": data.get("active_on_discord_mobile", False),
                "web": data.get("active_on_discord_web", False),
            },
            "listening_to_spotify": data.get("listening_to_spotify", False),
        }

    def _write(self, entry):
        """Append entry to today's daily JSONL file."""
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        log_file = self.log_dir / f"{today}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
