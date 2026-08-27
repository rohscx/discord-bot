"""Unit tests for DynamoDB game history without AWS network access."""

from datetime import datetime, timedelta, timezone
import unittest

from game_history import (
    DynamoGameHistory,
    TEMPLATES,
    context_status_line,
    game_key,
    member_pk,
    parse_utc_timestamp,
    session_sk,
    utc_timestamp,
)


NOW = datetime(2026, 8, 27, 20, 8, 15, 347000, tzinfo=timezone.utc)


class FakeTable:
    def __init__(self):
        self.items = {}
        self.query_items = []
        self.calls = []

    def get_item(self, **kwargs):
        self.calls.append(("get_item", kwargs))
        item = self.items.get((kwargs["Key"]["pk"], kwargs["Key"]["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, **kwargs):
        self.calls.append(("put_item", kwargs))
        item = kwargs["Item"]
        self.items[(item["pk"], item["sk"])] = item
        return {}

    def delete_item(self, **kwargs):
        self.calls.append(("delete_item", kwargs))
        self.items.pop((kwargs["Key"]["pk"], kwargs["Key"]["sk"]), None)
        return {}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {"Items": list(self.query_items)}

    def update_item(self, **kwargs):
        self.calls.append(("update_item", kwargs))
        values = kwargs["ExpressionAttributeValues"]
        self.items[(kwargs["Key"]["pk"], kwargs["Key"]["sk"])] = {
            "pk": kwargs["Key"]["pk"],
            "sk": kwargs["Key"]["sk"],
            "recent_template_ids": values[":ids"],
            "last_announced_at": values[":at"],
            "last_game_key": values[":game"],
            "schema_version": values[":version"],
        }
        return {}


def session_item(name, started_at, ended_at, seconds, expires_at=None):
    expires_at = expires_at or int((ended_at + timedelta(days=90)).timestamp())
    return {
        "pk": member_pk(10, 20),
        "sk": session_sk(started_at, name),
        "game_key": game_key(name),
        "game_name": name,
        "started_at": utc_timestamp(started_at),
        "ended_at": utc_timestamp(ended_at),
        "observed_seconds": seconds,
        "expires_at": expires_at,
        "schema_version": 1,
    }


class TestTimestampContract(unittest.TestCase):
    def test_fixed_width_utc_milliseconds(self):
        value = utc_timestamp(NOW)
        self.assertEqual(value, "2026-08-27T20:08:15.347Z")
        self.assertEqual(parse_utc_timestamp(value), NOW)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            utc_timestamp(datetime(2026, 8, 27))

    def test_variable_precision_rejected(self):
        with self.assertRaises(ValueError):
            parse_utc_timestamp("2026-08-27T20:08:15Z")

    def test_session_key_sorts_by_time_before_game(self):
        earlier = session_sk(NOW - timedelta(seconds=1), "Z Game")
        later = session_sk(NOW, "A Game")
        self.assertLess(earlier, later)


class TestTransitions(unittest.TestCase):
    def test_start_change_and_stop_create_bounded_sessions(self):
        table = FakeTable()
        history = DynamoGameHistory(table)

        self.assertTrue(history.record_transition(10, 20, "Mortal Shell II", NOW))
        state = table.items[(member_pk(10, 20), "state")]
        self.assertEqual(state["current_game"], "Mortal Shell II")

        changed_at = NOW + timedelta(hours=1)
        self.assertTrue(history.record_transition(10, 20, "ARC Raiders", changed_at))
        first_session = table.items[(member_pk(10, 20), session_sk(NOW, "Mortal Shell II"))]
        self.assertEqual(first_session["observed_seconds"], 3600)
        self.assertEqual(
            first_session["expires_at"],
            int((changed_at + timedelta(days=90)).timestamp()),
        )
        self.assertIn("ended_at", first_session)

        stopped_at = changed_at + timedelta(minutes=30)
        self.assertTrue(history.record_transition(10, 20, None, stopped_at))
        self.assertNotIn((member_pk(10, 20), "state"), table.items)
        second_session = table.items[(member_pk(10, 20), session_sk(changed_at, "ARC Raiders"))]
        self.assertEqual(second_session["observed_seconds"], 1800)

    def test_duplicate_presence_does_not_write(self):
        table = FakeTable()
        history = DynamoGameHistory(table)
        history.record_transition(10, 20, "Mortal Shell II", NOW)
        writes_before = len([call for call in table.calls if call[0] != "get_item"])
        self.assertFalse(history.record_transition(10, 20, "Mortal Shell II", NOW))
        writes_after = len([call for call in table.calls if call[0] != "get_item"])
        self.assertEqual(writes_before, writes_after)

    def test_stale_open_session_is_capped_at_24_hours(self):
        table = FakeTable()
        history = DynamoGameHistory(table)
        started_at = NOW - timedelta(days=19)
        table.items[(member_pk(10, 20), "state")] = {
            "pk": member_pk(10, 20),
            "sk": "state",
            "current_game": "Mortal Shell II",
            "started_at": utc_timestamp(started_at),
        }
        history.record_transition(10, 20, None, NOW)
        session = table.items[(member_pk(10, 20), session_sk(started_at, "Mortal Shell II"))]
        self.assertEqual(session["observed_seconds"], 24 * 3600)

    def test_opted_out_member_never_touches_table(self):
        table = FakeTable()
        history = DynamoGameHistory(table, excluded_member_ids={20})
        self.assertFalse(history.record_transition(10, 20, "Mortal Shell II", NOW))
        headline, context = history.announcement(10, 20, "Erou", "Lounge", "Mortal Shell II", NOW)
        self.assertIn("Erou", headline)
        self.assertEqual(context["kind"], "generic")
        self.assertEqual(table.calls, [])


class TestContextAndTemplates(unittest.TestCase):
    def test_recent_game_wins(self):
        table = FakeTable()
        table.query_items = [
            session_item("Mortal Shell II", NOW - timedelta(hours=3), NOW - timedelta(hours=1), 7200)
        ]
        context = DynamoGameHistory(table).historical_context(10, 20, NOW)
        self.assertEqual(context, {"kind": "recent", "game": "Mortal Shell II"})

    def test_favorite_uses_observed_seconds(self):
        table = FakeTable()
        table.query_items = [
            session_item("Short Game", NOW - timedelta(days=4), NOW - timedelta(days=3), 100),
            session_item("Long Game", NOW - timedelta(days=6), NOW - timedelta(days=5), 5000),
        ]
        context = DynamoGameHistory(table).historical_context(10, 20, NOW)
        self.assertEqual(context, {"kind": "favorite", "game": "Long Game"})

    def test_logically_expired_sessions_are_ignored(self):
        table = FakeTable()
        table.query_items = [
            session_item(
                "Expired Game",
                NOW - timedelta(hours=3),
                NOW - timedelta(hours=1),
                5000,
                expires_at=int(NOW.timestamp()) - 1,
            )
        ]
        self.assertIsNone(DynamoGameHistory(table).historical_context(10, 20, NOW))

    def test_last_three_templates_are_avoided(self):
        table = FakeTable()
        recent = [template_id for template_id, _ in TEMPLATES["current"][:3]]
        table.items[(member_pk(10, 20), "announcement")] = {
            "pk": member_pk(10, 20),
            "sk": "announcement",
            "recent_template_ids": recent,
        }
        _, context = DynamoGameHistory(table).announcement(
            10, 20, "Erou", "Lounge", "Mortal Shell II", NOW
        )
        updated = table.items[(member_pk(10, 20), "announcement")]["recent_template_ids"]
        self.assertEqual(context["kind"], "current")
        self.assertNotIn(updated[-1], recent)

    def test_status_labels_do_not_claim_history_is_current(self):
        recent = context_status_line({"kind": "recent", "game": "Mortal Shell II"}, "No activity")
        favorite = context_status_line({"kind": "favorite", "game": "ARC Raiders"}, "No activity")
        self.assertEqual(recent, "🎮 Recently spotted playing: Mortal Shell II")
        self.assertEqual(favorite, "🎮 Frequent haunt: ARC Raiders")


if __name__ == "__main__":
    unittest.main()
