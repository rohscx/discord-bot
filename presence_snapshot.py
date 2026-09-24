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
    write_payload(path, payload)


def write_payload(path, payload):
    """Atomically replace the private snapshot (never append history)."""
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


def build_members_snapshot(guilds, connected, excluded_ids=()):
    """Capture cache on the event loop; file I/O can run in a worker."""
    members = []
    unavailable_guilds = []
    if connected:
        for guild in guilds:
            if getattr(guild, "unavailable", False):
                unavailable_guilds.append(str(guild.id))
                continue
            for member in guild.members:
                if member.id in excluded_ids:
                    continue
                activities = []
                for activity in member.activities:
                    kind = getattr(activity.type, "value", activity.type)
                    if kind == 0 and activity.name:
                        activities.append({"type": "playing", "name": str(activity.name)[:256]})
                members.append({
                    "guild_id": str(guild.id), "member_id": str(member.id),
                    "username": str(member.name), "display_name": str(member.display_name),
                    "status": str(member.status), "activities": activities,
                })
    return {
        "schema": 2, "checked_at": time.time(), "connected": bool(connected),
        "members": members, "unavailable_guild_ids": unavailable_guilds,
    }


def read_snapshot(path, max_age=90, member=None, guild_id=None):
    try:
        payload = json.loads(Path(path).read_text())
        age = time.time() - float(payload["checked_at"])
        if not 0 <= age <= max_age or not payload.get("connected"):
            return {"available": False, "reason": "stale or disconnected"}
        if payload.get("schema") == 2:
            entries = payload["members"]
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) or not all(
                    isinstance(entry.get(key), str)
                    for key in ("guild_id", "member_id", "username", "display_name", "status")
                ) or not isinstance(entry.get("activities"), list)
                for entry in entries
            ):
                raise ValueError("invalid members")
            if guild_id is not None:
                entries = [entry for entry in entries if entry["guild_id"] == str(guild_id)]
            if member is not None:
                query = str(member).casefold()
                entries = [entry for entry in entries if query in (
                    entry["member_id"], entry["username"].casefold(),
                    entry["display_name"].casefold(),
                )]
            if (member is not None or guild_id is not None) and not entries:
                return {"available": False, "reason": "member or guild unavailable"}
            return {**payload, "available": True, "members": entries}
        if payload.get("schema") != 1 or not payload.get("member_found"):
            return {"available": False, "reason": "member unavailable"}
        if member is not None and str(member) != payload.get("member_id"):
            return {"available": False, "reason": "member unavailable"}
        if guild_id is not None and str(guild_id) != payload.get("guild_id"):
            return {"available": False, "reason": "guild unavailable"}
        return {**payload, "available": True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"available": False, "reason": "snapshot unavailable or invalid"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--member", help="Exact member ID, username or display name")
    parser.add_argument("--guild", help="Restrict results to this guild ID")
    args = parser.parse_args()
    print(json.dumps(read_snapshot(args.path, member=args.member, guild_id=args.guild), indent=2))
