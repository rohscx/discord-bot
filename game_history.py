"""DynamoDB-backed game history and personalized announcement helpers."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import re
import unicodedata

from boto3.dynamodb.conditions import Key


SCHEMA_VERSION = 1
SESSION_RETENTION_DAYS = 90
RECENT_GAME_HOURS = 24
FAVORITE_GAME_DAYS = 30
MAX_OBSERVED_SESSION_HOURS = 24

TEMPLATES = {
    "generic": (
        ("generic_join", "🔊 **{member}** has joined **{channel}**."),
        ("generic_breach", "🔊 **{member}** has breached **{channel}**."),
        ("generic_noise", "🔊 **{member}** entered **{channel}**. The noise floor has increased."),
        ("generic_arrival", "🔊 **{member}** arrived in **{channel}**. Try to look surprised."),
    ),
    "current": (
        ("current_join", "🔊 **{member}** has joined **{channel}**, with **{game}** still warm."),
        ("current_materialize", "🔊 **{member}** materialized in **{channel}** from **{game}**."),
        ("current_checkpoint", "🔊 **{member}** reached the **{channel}** checkpoint via **{game}**."),
        ("current_fast_travel", "🔊 **{member}** fast-traveled from **{game}** to **{channel}**."),
    ),
    "recent": (
        ("recent_release", "🔊 **{member}** has arrived in **{channel}**. **{game}** released them temporarily."),
        ("recent_return", "🔊 **{member}** returned to **{channel}** after a recent encounter with **{game}**."),
        ("recent_survivor", "🔊 **{member}** survived **{game}** and made it to **{channel}**."),
        ("recent_detour", "🔊 **{member}** took a detour from **{game}** into **{channel}**."),
    ),
    "favorite": (
        ("favorite_haunt", "🔊 **{member}** escaped their usual **{game}** haunt for **{channel}**."),
        ("favorite_intermission", "🔊 **{member}** called an intermission from **{game}** and joined **{channel}**."),
        ("favorite_spawn", "🔊 **{member}** spawned in **{channel}**, suspiciously far from **{game}**."),
        ("favorite_shore_leave", "🔊 **{member}** is on shore leave from **{game}** in **{channel}**."),
    ),
}


def utc_timestamp(value):
    """Serialize an aware datetime as fixed-width UTC RFC 3339 milliseconds."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def parse_utc_timestamp(value):
    """Parse the exact timestamp format used in DynamoDB sort keys."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        raise ValueError("timestamp must use YYYY-MM-DDTHH:mm:ss.SSSZ")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def game_key(name):
    """Return a stable, compact key while preserving the display name separately."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if slug:
        return slug[:80]
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def member_pk(guild_id, member_id):
    return f"guild#{guild_id}#member#{member_id}"


def session_sk(started_at, name):
    return f"session#{utc_timestamp(started_at)}#{game_key(name)}"


def choose_template(member_id, context_kind, game_name, recent_ids, now):
    """Choose a daily deterministic template, excluding the last three when possible."""
    pool = TEMPLATES[context_kind]
    recent = set((recent_ids or [])[-3:])
    eligible = [template for template in pool if template[0] not in recent] or list(pool)
    seed = f"{member_id}|{context_kind}|{game_name or ''}|{now.astimezone(timezone.utc).date()}"
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(eligible)
    return eligible[index]


class DynamoGameHistory:
    """Persistence facade for observed game transitions and announcement state."""

    def __init__(self, table, excluded_member_ids=None):
        self.table = table
        self.excluded_member_ids = set(excluded_member_ids or ())

    def is_excluded(self, member_id):
        return int(member_id) in self.excluded_member_ids

    def record_transition(self, guild_id, member_id, new_game, now=None):
        """Close the prior observed session and start a new one only on change."""
        if self.is_excluded(member_id):
            return False
        now = now or datetime.now(timezone.utc)
        pk = member_pk(guild_id, member_id)
        current = self.table.get_item(
            Key={"pk": pk, "sk": "state"}, ConsistentRead=False
        ).get("Item")
        previous_game = current.get("current_game") if current else None
        if previous_game == new_game:
            return False

        if current and previous_game:
            started_at = parse_utc_timestamp(current["started_at"])
            if started_at > now:
                started_at = now
            observed_seconds = min(
                max(0, int((now - started_at).total_seconds())),
                MAX_OBSERVED_SESSION_HOURS * 3600,
            )
            expires_at = int((now + timedelta(days=SESSION_RETENTION_DAYS)).timestamp())
            self.table.put_item(Item={
                "pk": pk,
                "sk": session_sk(started_at, previous_game),
                "game_key": game_key(previous_game),
                "game_name": previous_game,
                "started_at": utc_timestamp(started_at),
                "ended_at": utc_timestamp(now),
                "observed_seconds": observed_seconds,
                "expires_at": expires_at,
                "schema_version": SCHEMA_VERSION,
            })

        if new_game:
            self.table.put_item(Item={
                "pk": pk,
                "sk": "state",
                "current_game": new_game,
                "current_game_key": game_key(new_game),
                "started_at": utc_timestamp(now),
                "last_observed_at": utc_timestamp(now),
                "schema_version": SCHEMA_VERSION,
            })
        elif current:
            self.table.delete_item(Key={"pk": pk, "sk": "state"})
        return True

    def historical_context(self, guild_id, member_id, now=None):
        """Return recent or 30-day favorite game context via one bounded Query."""
        if self.is_excluded(member_id):
            return None
        now = now or datetime.now(timezone.utc)
        window_start = now - timedelta(days=FAVORITE_GAME_DAYS)
        response = self.table.query(
            KeyConditionExpression=(
                Key("pk").eq(member_pk(guild_id, member_id))
                & Key("sk").between(
                    f"session#{utc_timestamp(window_start)}",
                    f"session#{utc_timestamp(now)}\uffff",
                )
            ),
            ConsistentRead=False,
            ScanIndexForward=False,
        )
        sessions = [
            item for item in response.get("Items", [])
            if int(item.get("expires_at", 0)) > int(now.timestamp())
        ]
        if not sessions:
            return None

        newest = max(sessions, key=lambda item: item["ended_at"])
        if parse_utc_timestamp(newest["ended_at"]) >= now - timedelta(hours=RECENT_GAME_HOURS):
            return {"kind": "recent", "game": newest["game_name"]}

        totals = defaultdict(int)
        display_names = {}
        for item in sessions:
            key = item["game_key"]
            totals[key] += int(item.get("observed_seconds", 0))
            display_names[key] = item["game_name"]
        favorite = max(totals, key=totals.get)
        return {"kind": "favorite", "game": display_names[favorite]}

    def announcement(self, guild_id, member_id, member_name, channel_name, current_game=None, now=None):
        """Build and persist a personalized announcement, with generic opt-out behavior."""
        now = now or datetime.now(timezone.utc)
        excluded = self.is_excluded(member_id)
        context = {"kind": "current", "game": current_game} if current_game and not excluded else None
        if not context and not excluded:
            context = self.historical_context(guild_id, member_id, now)
        context = context or {"kind": "generic", "game": None}

        recent_ids = []
        pk = member_pk(guild_id, member_id)
        if not excluded:
            item = self.table.get_item(
                Key={"pk": pk, "sk": "announcement"}, ConsistentRead=False
            ).get("Item", {})
            recent_ids = list(item.get("recent_template_ids", []))

        template_id, template = choose_template(
            member_id, context["kind"], context["game"], recent_ids, now
        )
        headline = template.format(member=member_name, channel=channel_name, game=context["game"])

        if not excluded:
            updated_ids = (recent_ids + [template_id])[-3:]
            self.table.update_item(
                Key={"pk": pk, "sk": "announcement"},
                UpdateExpression=(
                    "SET recent_template_ids = :ids, last_announced_at = :at, "
                    "last_game_key = :game, schema_version = :version"
                ),
                ExpressionAttributeValues={
                    ":ids": updated_ids,
                    ":at": utc_timestamp(now),
                    ":game": game_key(context["game"]) if context["game"] else "",
                    ":version": SCHEMA_VERSION,
                },
            )
        return headline, context


def context_status_line(context, live_activity):
    if context["kind"] == "current":
        return f"🎮 Currently playing: {context['game']}"
    if context["kind"] == "recent":
        return f"🎮 Recently spotted playing: {context['game']}"
    if context["kind"] == "favorite":
        return f"🎮 Frequent haunt: {context['game']}"
    return f"🎮 Status: {live_activity}"
