# Private presence bridge

Opt-in bridge for the assistant to read a single member's current Discord game,
without a network listener, new Discord messages, tokens, or activity history.
The existing Discord Gateway presence intent must be enabled.

Deployment environment:

```
PRESENCE_SNAPSHOT_PATH=/home/ec2-user/.openclaw/workspace/data/discord-presence/erou.json
PRESENCE_MEMBER_ID=591452415266521089
PRESENCE_GUILD_ID=1209211111446937670
```

The bot publishes every 30 seconds from its live cache. All three settings are
required; default installations do not export anything. Member tracking opt-outs
are respected. Each atomic snapshot is mode 0600 and includes connection state,
cache-check timestamp, presence status and playing activity names only.
No custom statuses, listening titles, streaming URLs or other members are exported.

Assistant read command after deployment:

```
python3 /home/ec2-user/.openclaw/workspace/discord-bot-release/presence_snapshot.py /home/ec2-user/.openclaw/workspace/data/discord-presence/erou.json
```

The reader rejects snapshots older than 90 seconds, disconnected snapshots,
missing members and malformed files. Available with an empty activities array means
Discord reports no playing activity, not proof the person is not playing.
A disconnected bot can leave a last snapshot readable until its freshness limit;
the heartbeat samples connected state every 30 seconds. Timestamps reflect cache
checks, not necessarily a newly received Discord event.

Merge through the normal PR workflow, deploy the reviewed revision, configure the
three environment settings and restart lounge-bot. Read the snapshot to prove the
live connection; do not claim success based only on unit tests. Rollback: unset
PRESENCE_SNAPSHOT_PATH and restart. Delete the snapshot if disabling permanently.
