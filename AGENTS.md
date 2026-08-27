# AGENTS.md — Architectural Decisions & Reasoning

## Contribution Workflow

**All changes go through branches and pull requests — no direct commits to `main`.**

- Branch naming: `rev/<short-description>` for Rev's changes
- Open a PR for review before merging
- Erou merges after review

**Why:** Maintains a clean history, enables code review, and keeps `main` stable. Even for solo/bot changes — the PR is the review checkpoint.

## Gateway Reconnect: Cooldown Preservation

**Decision (2026-03-03):** Preserve `member_join_times` across gateway reconnects. Do NOT clear the cache on `on_resumed`.

**History:** Originally (PR #3, 2026-02-15) the bot cleared the cooldown cache on every gateway resume to prevent stale timestamps from corrupting cooldown logic. However, production logs showed gateway disconnects every 1–3 hours, which meant the cooldown was effectively never enforced — the cache was wiped before any member could hit the threshold.

**Current approach — two layers for stale event protection:**
1. **Channel membership validation** — before notifying, verify the member is actually in the channel's member list. Catches phantom joins from stale/replayed events.
2. **Resume grace period** — 10-second suppression window after each gateway resume to absorb any burst of replayed voice state events.

**Why cache clear was removed:** The membership check (layer 1) already handles the dangerous case (false notifications from stale events). Clearing the cache was belt-and-suspenders, but the cost — losing all cooldown state every 1–3 hours — far outweighed the theoretical benefit. With the cache preserved, the spam cooldown actually works as intended.

**Pruning:** Expired entries (older than TIME_THRESHOLD) are pruned on each join event to prevent unbounded memory growth.

## Cooldown Window (TIME_THRESHOLD)

**Default:** 7200 seconds (2 hours).

**History:** Briefly changed to 3600 on 2026-02-21, but reverted to 7200. The 1-hour window wasn't meaningfully tested because gateway reconnects were clearing the cache every 1–3 hours anyway (see above). With the cache now preserved across reconnects, the 2-hour window is the effective cooldown.

**Reasoning:** 2 hours prevents notification spam from members hopping in and out during extended sessions. If the window proves too aggressive now that cooldowns actually survive reconnects, it can be tuned via the `TIME_THRESHOLD` environment variable.

## Office Hours (@here Suppression)

**Decision:** Notifications still post outside office hours, but without the `@here` ping.

**Why not just silence entirely?** Late-night sessions are still worth logging — someone checking the channel in the morning can see who was on. The ping is what's disruptive, not the message itself.

**Default window:** 06:00–22:30 US/Eastern. Supports overnight ranges (e.g., 22:00–06:00).

## Voice Channel Matching

**Decision (2026-03-03):** Match the target voice channel by ID (`VOICE_CHANNEL_ID`) with a fallback to name (`VOICE_CHANNEL_NAME`).

**Why:** Channel names can change and aren't unique — two voice channels could share the same name. Channel IDs are immutable and unambiguous. The name fallback is kept for backwards compatibility and ease of initial setup (names are human-readable; IDs require Developer Mode to copy).

## Stale Event Detection

**Decision:** Compare channel IDs instead of channel objects for join/leave detection.

**Why:** discord.py caches VoiceState objects. After a reconnect, `before.channel` and `after.channel` may be different Python objects representing the same channel, causing reference equality (`is`) and even `==` comparisons to behave unexpectedly. ID comparison is always reliable.

## Logging Architecture

**Decision:** Dual-output logging — console (INFO) + rotating file (DEBUG).

**Why:** Console output goes to journald via systemd, which is great for `journalctl` but has limited retention. The rotating file handler captures DEBUG-level detail for post-incident analysis without unbounded disk growth (5MB × 3 backups = 20MB max).

**Structured prefixes:** `JOIN`, `LEAVE`, `SUPPRESS`, `STALE`, `NOTIFY` — designed for `grep` workflows.

## DynamoDB Game History

**Decision (2026-08-27):** Use the existing `openclaw-discord-bot-state` table;
do not create a table or GSI. Member data uses
`pk=guild#<guild_id>#member#<member_id>` with `state`, `announcement`, and
`session#<YYYY-MM-DDTHH:mm:ss.SSSZ>#<game-key>` sort keys.

The timestamp format is a fixed-width UTC RFC 3339 requirement because lexical
sort order must equal chronological order. Timestamp-first deliberately favors
bounded recent-history queries over querying one game across arbitrary dates.

Every session requires `ended_at` and a numeric `expires_at` 90 days later.
DynamoDB TTL is asynchronous, so application reads must also reject logically
expired records. Use `Query`, never `Scan`; 5 RCU/WCU is shared table capacity.
Writes occur on game transitions only, startup reconciliation is rate-limited,
and AWS failures must degrade to generic/live announcements without blocking the
Discord notification.
