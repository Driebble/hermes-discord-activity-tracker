---
name: discord-activity-report
description: Generate and deliver daily Discord activity reports
tags: [discord, activity, report, daily]
---

# Discord Activity Report

Generate a daily Discord activity report and deliver to the home channel.

## Steps

1. **Query data using the discord_activity tool:**
   - `discord_activity(query="stats", days=1)` — get aggregated stats
   - `discord_activity(query="timeline", days=1)` — get activity timeline

2. **If the tool isn't available**, run the aggregator as fallback:
   ```bash
   python "C:\Users\Drie\AppData\Local\hermes\profiles\aura\scripts\discord-activity-aggregator.py" 1
   ```

3. **Parse the output and extract key metrics:**
   - Total online time
   - Spotify listening time and top songs
   - Games/activities detected
   - Platform usage (desktop/mobile/web)
   - Status distribution (online/idle/offline)

4. **Format a clean Discord report using markdown:**
   - Use bold headers
   - Use bullet lists
   - Keep it concise but informative

5. **Send the report** to the home channel using `send_message` with target="discord:1506522557690679368"

## Report Template

```
**Daily Discord Activity Report**

**Online Time:** X hours Y minutes
**Platforms:** Desktop: Xm | Mobile: Xm | Web: Xm

**Spotify:**
- Top tracks: ...
- Total listening: Xm

**Activities:**
- Game: X sessions (Ym)
- ...

**Status:**
- Online: Xm
- Idle: Xm
- Offline: Xm

**Timeline:**
- **08:30–09:15** · 🟢 · Playing Valorant · 🎵 Days of Thunder — The Midnight
- **09:15–11:40** · 🟢 · Playing Valorant
- **11:40–12:05** · 🟡 · Idle
- **12:05–13:00** · 🟢 · Online (no activity detected)
- **13:00–13:05** · ⚫ · Off
- **13:05–15:30** · 🟢 · Playing Valorant · 🎵 The Night — Avicii
```

## Timeline Formatting Rules

1. **Status indicators:**
   - 🟢 = online
   - 🟡 = idle
   - ⚫ = off/disconnected

2. **Activity display:**
   - Main activity: "Playing {name}" for games, just the name for others
   - No activities: "Online (no activity detected)"

3. **Spotify:** 🎵 {song} — {artist}

4. **Time format:** HH:MM in 24h format (WIB), start–end: "08:30–09:15"
