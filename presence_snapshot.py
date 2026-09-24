"""Private, bounded live-presence bridge. No tokens, messages or history."""
import json
import os
import tempfile
import time
from pathlib import Path


def write_snapshot(path, guild, member_id, connected, excluded=False):
    member = guild.get_member(member_id) if guild and connected and not excluded else None
    activities = []
    if member:
        for activity in member.activities:
            kind = getattr(activity.type, "value", activity.type)
            # Only game names; exclude custom status, Spotify and streaming URLs.
            if kind == 0 and activity.name:
                activities.append({"type": "playing", "name": str(activity.name)[:256]})
    payload = {
        "schema": 1, "checked_at": time.time(),
        "connected": bool(connected), "member_found": member is not None,
        "excluded": excluded, "member_id": str(member_id),
        "guild_id": str(guild.id) if guild else None,
        "status": str(member.status) if member else "unknown",
        "activities": activities,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".presence-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream)
        os.replace(temporary, target)  # mkstemp mode 0600 is retained
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_snapshot(path, max_age=90):
    try:
        payload = json.loads(Path(path).read_text())
        age = time.time() - float(payload["checked_at"])
        if not 0 <= age <= max_age or not payload.get("connected") or not payload.get("member_found"):
            return {"available": False, "reason": "stale, disconnected, or member unavailable"}
        return {"available": True, **payload}
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "reason": "snapshot unavailable or invalid"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    args = parser.parse_args()
    print(json.dumps(read_snapshot(args.path), indent=2))
