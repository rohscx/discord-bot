# AGENTS.md — Architectural Decisions & Reasoning

## Contribution Workflow

**All changes go through branches and pull requests — no direct commits to `main`.**

- Branch naming: `rev/<short-description>` for Rev's changes
- Open a PR for review before merging
- Erou merges after review

**Why:** Maintains a clean history, enables code review, and keeps `main` stable. Even for solo/bot changes — the PR is the review checkpoint.

## Gateway Reconnect: Cache Clear vs Persistent Cooldowns

**Decision:** Clear `member_join_times` on `on_resumed` (gateway reconnect).

**Context (PR #3, 2026-02-15):** After prolonged uptime, the bot was posting join notifications when members *left* the channel. Root cause: silent gateway reconnects replayed stale voice state events with inverted before/after states.

**Fix applied — two layers:**
1. **Channel membership validation** — before notifying, verify the member is actually in the channel's member list. Catches phantom joins from stale events.
2. **Cache clear on resume** — wipe `member_join_times` to prevent stale timestamps from corrupting cooldown logic after reconnects.

**Trade-off:**
- **With cache clear:** Cooldowns reset on every gateway reconnect. If someone joins, disconnects briefly (gateway blip), and rejoins, they may trigger a duplicate notification even within the cooldown window. Gateway reconnects happen regularly (Discord maintenance, network blips).
- **Without cache clear:** Cooldowns survive reconnects, but stale timestamps could theoretically suppress a legitimate notification (bot thinks user joined recently based on pre-reconnect data when they didn't).
- **Assessment (2026-02-21):** The membership check (layer 1) handles the dangerous case (false notifications). The cache clear is belt-and-suspenders. Removing it would make cooldowns more reliable at the cost of a theoretical edge case. Keeping it for now — revisit if duplicate notifications become noisy.

## Cooldown Window (TIME_THRESHOLD)

**Default:** 3600 seconds (1 hour) — changed from 7200 (2 hours) on 2026-02-21.

**Reasoning:** 2 hours was too aggressive for suppression. If someone hops into the Lounge, leaves for lunch, and comes back an hour later, that's a meaningful "session" worth notifying about. 1 hour balances spam prevention against missing real activity.

**Note:** Because of the cache clear on gateway reconnects (see above), the effective cooldown may be shorter than configured if reconnects are frequent.

## Office Hours (@here Suppression)

**Decision:** Notifications still post outside office hours, but without the `@here` ping.

**Why not just silence entirely?** Late-night sessions are still worth logging — someone checking the channel in the morning can see who was on. The ping is what's disruptive, not the message itself.

**Default window:** 06:00–22:30 US/Eastern. Supports overnight ranges (e.g., 22:00–06:00).

## Stale Event Detection

**Decision:** Compare channel IDs instead of channel objects for join/leave detection.

**Why:** discord.py caches VoiceState objects. After a reconnect, `before.channel` and `after.channel` may be different Python objects representing the same channel, causing reference equality (`is`) and even `==` comparisons to behave unexpectedly. ID comparison is always reliable.

## Logging Architecture

**Decision:** Dual-output logging — console (INFO) + rotating file (DEBUG).

**Why:** Console output goes to journald via systemd, which is great for `journalctl` but has limited retention. The rotating file handler captures DEBUG-level detail for post-incident analysis without unbounded disk growth (5MB × 3 backups = 20MB max).

**Structured prefixes:** `JOIN`, `LEAVE`, `SUPPRESS`, `STALE`, `NOTIFY` — designed for `grep` workflows.
