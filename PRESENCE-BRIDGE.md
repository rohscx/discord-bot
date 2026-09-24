# Private presence bridge

Opt-in local snapshots let the assistant read current Discord presence without a
network listener, new Discord messages, credentials, or activity history.
Discord Gateway member and presence intents must be enabled.

## All cached members

Set the following in the bot deployment environment and restart lounge-bot:

```
PRESENCE_MEMBERS_SNAPSHOT_PATH=/home/ec2-user/.openclaw/workspace/data/discord-presence/members.json
```

Every 30 seconds the bot exports members cached across all its available guilds,
excluding GAME_TRACKING_EXCLUDED_MEMBER_IDS. Each member includes guild/member ID,
username, display name, presence status, and playing activity names only.
Custom statuses, listening titles, and streaming URLs are not exported.
Unavailable guilds are omitted and listed separately. Members shared by multiple
guilds retain one record per guild; ambiguous names return every exact match.

Read all members, or filter by exact case-insensitive name or member ID:

```
python3 /home/ec2-user/.openclaw/workspace/discord-bot-release/presence_snapshot.py /home/ec2-user/.openclaw/workspace/data/discord-presence/members.json
python3 /home/ec2-user/.openclaw/workspace/discord-bot-release/presence_snapshot.py /home/ec2-user/.openclaw/workspace/data/discord-presence/members.json --member Merda
```

Optional `--guild GUILD_ID` restricts results to one server.

## Legacy single-member feed

These settings remain supported independently, preserving existing consumers:

```
PRESENCE_SNAPSHOT_PATH=/home/ec2-user/.openclaw/workspace/data/discord-presence/erou.json
PRESENCE_MEMBER_ID=591452415266521089
PRESENCE_GUILD_ID=1209211111446937670
```

## Freshness and privacy

Default installations export nothing. Atomic snapshots retain mode 0600 and
replace rather than append history. Readers reject snapshots older than 90 seconds,
disconnected snapshots, missing members, and malformed files. A disconnect may
leave the last snapshot readable until the next 30-second sample or freshness
expiry. Timestamps represent cache checks, not newly received Discord events.

An empty activities array means Discord reports no playing activity, not proof
the member is not playing. Discord invisible users appear offline; the feed
cannot distinguish them. Cached members are not a guarantee of complete server
membership or fresh per-member presence.

Normal changes use a branch and PR, with Erou merging. Authorized local deployment
can precede merge. Verify the live snapshot after restart, not only unit tests.
Rollback: restore previous code and environment and restart lounge-bot, or unset
the relevant snapshot setting and remove the disabled snapshot.
