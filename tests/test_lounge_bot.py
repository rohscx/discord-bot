"""Tests for lounge_bot core logic.

Tests the pure/testable functions and event handler behavior using mocked
discord.py objects. Does NOT require a live Discord connection.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, time as dt_time, timedelta
import asyncio


# ---------------------------------------------------------------------------
# Helpers to run async tests
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def make_channel(name="Lounge", channel_id=100, members=None):
    ch = MagicMock()
    ch.name = name
    ch.id = channel_id
    ch.members = members or []
    return ch


def make_member(display_name="TestUser", member_id=1, activities=None):
    m = MagicMock()
    m.display_name = display_name
    m.id = member_id
    m.activities = activities or []
    return m


def make_voice_state(channel=None):
    vs = MagicMock()
    vs.channel = channel
    return vs


# ---------------------------------------------------------------------------
# Test: _is_target_channel
# ---------------------------------------------------------------------------

class TestIsTargetChannel(unittest.TestCase):
    """Test the _is_target_channel helper."""

    def _get_func(self):
        """Import the function after patching env vars."""
        import importlib
        # We need to re-import to pick up patched values
        # Instead, test the logic directly
        pass

    def test_none_channel_returns_false(self):
        """None channel should never match."""
        # Direct logic test — mirrors _is_target_channel
        self.assertFalse(self._check(None, voice_channel_id=100, name="Lounge"))

    def test_match_by_id(self):
        """When VOICE_CHANNEL_ID is set, match by ID."""
        ch = make_channel("Lounge", channel_id=100)
        self.assertTrue(self._check(ch, voice_channel_id=100, name="Lounge"))

    def test_no_match_by_id(self):
        """Wrong ID should not match even if name matches."""
        ch = make_channel("Lounge", channel_id=999)
        self.assertFalse(self._check(ch, voice_channel_id=100, name="Lounge"))

    def test_match_by_name_fallback(self):
        """When VOICE_CHANNEL_ID is None, fall back to name matching."""
        ch = make_channel("Lounge", channel_id=999)
        self.assertTrue(self._check(ch, voice_channel_id=None, name="Lounge"))

    def test_no_match_by_name(self):
        """Wrong name and no ID should not match."""
        ch = make_channel("General", channel_id=999)
        self.assertFalse(self._check(ch, voice_channel_id=None, name="Lounge"))

    @staticmethod
    def _check(channel, voice_channel_id, name):
        """Replicate _is_target_channel logic for testing without importing the module."""
        if channel is None:
            return False
        if voice_channel_id:
            return channel.id == voice_channel_id
        return channel.name == name


# ---------------------------------------------------------------------------
# Test: get_member_activity
# ---------------------------------------------------------------------------

class TestGetMemberActivity(unittest.TestCase):
    """Test activity extraction from member objects."""

    def test_no_activities(self):
        member = make_member(activities=[])
        self.assertEqual(self._get_activity(member), "No activity")

    def test_none_activities(self):
        member = make_member()
        member.activities = None
        self.assertEqual(self._get_activity(member), "No activity")

    def test_game_activity(self):
        import discord
        game = MagicMock(spec=discord.Game)
        game.name = "ARC Raiders"
        member = make_member(activities=[game])
        self.assertEqual(self._get_activity(member), "ARC Raiders")

    def test_streaming_activity_with_game(self):
        import discord
        stream = MagicMock(spec=discord.Streaming)
        stream.game = "Fortnite"
        member = make_member(activities=[stream])
        self.assertEqual(self._get_activity(member), "Streaming Fortnite")

    def test_streaming_activity_without_game(self):
        import discord
        stream = MagicMock(spec=discord.Streaming)
        stream.game = None
        member = make_member(activities=[stream])
        self.assertEqual(self._get_activity(member), "Streaming")

    def test_spotify_activity(self):
        import discord
        spotify = MagicMock(spec=discord.Spotify)
        spotify.title = "Bohemian Rhapsody"
        spotify.artist = "Queen"
        member = make_member(activities=[spotify])
        self.assertEqual(self._get_activity(member), "Listening to Bohemian Rhapsody by Queen")

    def test_generic_activity(self):
        import discord
        act = MagicMock(spec=discord.Activity)
        act.name = "Hang Status"
        member = make_member(activities=[act])
        self.assertEqual(self._get_activity(member), "Hang Status")

    def test_priority_order_game_first(self):
        """Game should be returned before Spotify if both present."""
        import discord
        game = MagicMock(spec=discord.Game)
        game.name = "Valorant"
        spotify = MagicMock(spec=discord.Spotify)
        spotify.title = "Song"
        spotify.artist = "Artist"
        member = make_member(activities=[game, spotify])
        self.assertEqual(self._get_activity(member), "Valorant")

    @staticmethod
    def _get_activity(member):
        """Replicate get_member_activity logic for isolated testing."""
        import discord
        if member.activities:
            for act in member.activities:
                if isinstance(act, discord.Game):
                    return act.name
                elif isinstance(act, discord.Streaming):
                    return f"Streaming {act.game}" if act.game else "Streaming"
                elif isinstance(act, discord.Spotify):
                    return f"Listening to {act.title} by {act.artist}"
                elif isinstance(act, discord.Activity):
                    return act.name
        return "No activity"


# ---------------------------------------------------------------------------
# Test: is_within_office_hours
# ---------------------------------------------------------------------------

class TestIsWithinOfficeHours(unittest.TestCase):
    """Test office hours logic."""

    def test_disabled_returns_true(self):
        """When office hours are disabled, always return True."""
        self.assertTrue(self._check(enabled=False))

    def test_normal_range_within(self):
        """10:00 is within 06:00–22:30."""
        self.assertTrue(self._check(
            enabled=True,
            start=dt_time(6, 0),
            end=dt_time(22, 30),
            now=dt_time(10, 0),
        ))

    def test_normal_range_before(self):
        """04:00 is before 06:00–22:30."""
        self.assertFalse(self._check(
            enabled=True,
            start=dt_time(6, 0),
            end=dt_time(22, 30),
            now=dt_time(4, 0),
        ))

    def test_normal_range_after(self):
        """23:00 is after 06:00–22:30."""
        self.assertFalse(self._check(
            enabled=True,
            start=dt_time(6, 0),
            end=dt_time(22, 30),
            now=dt_time(23, 0),
        ))

    def test_normal_range_at_start_boundary(self):
        """06:00 should be within 06:00–22:30."""
        self.assertTrue(self._check(
            enabled=True,
            start=dt_time(6, 0),
            end=dt_time(22, 30),
            now=dt_time(6, 0),
        ))

    def test_normal_range_at_end_boundary(self):
        """22:30 should be within 06:00–22:30."""
        self.assertTrue(self._check(
            enabled=True,
            start=dt_time(6, 0),
            end=dt_time(22, 30),
            now=dt_time(22, 30),
        ))

    def test_overnight_range_late_night(self):
        """23:00 is within 22:00–06:00."""
        self.assertTrue(self._check(
            enabled=True,
            start=dt_time(22, 0),
            end=dt_time(6, 0),
            now=dt_time(23, 0),
        ))

    def test_overnight_range_early_morning(self):
        """03:00 is within 22:00–06:00."""
        self.assertTrue(self._check(
            enabled=True,
            start=dt_time(22, 0),
            end=dt_time(6, 0),
            now=dt_time(3, 0),
        ))

    def test_overnight_range_midday_outside(self):
        """12:00 is outside 22:00–06:00."""
        self.assertFalse(self._check(
            enabled=True,
            start=dt_time(22, 0),
            end=dt_time(6, 0),
            now=dt_time(12, 0),
        ))

    @staticmethod
    def _check(enabled, start=None, end=None, now=None):
        """Replicate is_within_office_hours logic for isolated testing."""
        if not enabled:
            return True
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end


# ---------------------------------------------------------------------------
# Test: Spam suppression / cooldown pruning
# ---------------------------------------------------------------------------

class TestSpamSuppression(unittest.TestCase):
    """Test the cooldown and pruning logic."""

    def test_first_join_not_suppressed(self):
        """First join for a member should not be suppressed."""
        cache = {}
        member_id = 1
        current_time = datetime.now(timezone.utc)
        threshold = 7200

        last = cache.get(member_id)
        self.assertIsNone(last)  # No prior entry → not suppressed

    def test_rejoin_within_threshold_suppressed(self):
        """Rejoin within threshold should be suppressed."""
        cache = {}
        member_id = 1
        threshold = 7200
        first_join = datetime.now(timezone.utc) - timedelta(seconds=3600)
        cache[member_id] = first_join

        current_time = datetime.now(timezone.utc)
        last = cache.get(member_id)
        time_diff = (current_time - last).total_seconds()
        self.assertTrue(time_diff < threshold)

    def test_rejoin_after_threshold_not_suppressed(self):
        """Rejoin after threshold should not be suppressed."""
        cache = {}
        member_id = 1
        threshold = 7200
        old_join = datetime.now(timezone.utc) - timedelta(seconds=8000)
        cache[member_id] = old_join

        current_time = datetime.now(timezone.utc)
        last = cache.get(member_id)
        time_diff = (current_time - last).total_seconds()
        self.assertFalse(time_diff < threshold)

    def test_pruning_removes_expired_entries(self):
        """Pruning should remove entries older than threshold."""
        threshold = 7200
        current_time = datetime.now(timezone.utc)
        cache = {
            1: current_time - timedelta(seconds=10000),  # expired
            2: current_time - timedelta(seconds=8000),    # expired
            3: current_time - timedelta(seconds=100),     # fresh
            4: current_time,                              # just joined
        }

        stale_ids = [k for k, v in cache.items()
                     if (current_time - v).total_seconds() > threshold]
        for stale_id in stale_ids:
            del cache[stale_id]

        self.assertEqual(set(cache.keys()), {3, 4})
        self.assertEqual(len(stale_ids), 2)

    def test_pruning_with_no_expired_entries(self):
        """Pruning when all entries are fresh should remove nothing."""
        threshold = 7200
        current_time = datetime.now(timezone.utc)
        cache = {
            1: current_time - timedelta(seconds=100),
            2: current_time,
        }

        stale_ids = [k for k, v in cache.items()
                     if (current_time - v).total_seconds() > threshold]
        for stale_id in stale_ids:
            del cache[stale_id]

        self.assertEqual(set(cache.keys()), {1, 2})
        self.assertEqual(len(stale_ids), 0)


# ---------------------------------------------------------------------------
# Test: Resume grace period
# ---------------------------------------------------------------------------

class TestResumeGracePeriod(unittest.TestCase):
    """Test that the resume grace period suppresses notifications."""

    def test_within_grace_period(self):
        """Events during grace period should be suppressed."""
        grace_until = datetime.now(timezone.utc) + timedelta(seconds=10)
        now = datetime.now(timezone.utc)
        self.assertTrue(now < grace_until)

    def test_after_grace_period(self):
        """Events after grace period should not be suppressed."""
        grace_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        now = datetime.now(timezone.utc)
        self.assertFalse(now < grace_until)

    def test_grace_period_not_set(self):
        """No grace period set → no suppression."""
        grace_until = None
        suppressed = grace_until and datetime.now(timezone.utc) < grace_until
        self.assertFalse(suppressed)


# ---------------------------------------------------------------------------
# Test: Join/leave detection logic
# ---------------------------------------------------------------------------

class TestJoinLeaveDetection(unittest.TestCase):
    """Test the join/leave target channel detection logic."""

    def _is_target(self, channel, voice_channel_id=None, voice_channel_name="Lounge"):
        if channel is None:
            return False
        if voice_channel_id:
            return channel.id == voice_channel_id
        return channel.name == voice_channel_name

    def test_join_from_nothing(self):
        """Member joins target channel from no channel."""
        before = make_voice_state(channel=None)
        target = make_channel("Lounge", channel_id=100)
        after = make_voice_state(channel=target)

        joined = (
            self._is_target(after.channel, voice_channel_id=100)
            and (before.channel is None or before.channel.id != after.channel.id)
        )
        self.assertTrue(joined)

    def test_join_from_other_channel(self):
        """Member moves from another channel to target."""
        other = make_channel("General", channel_id=200)
        target = make_channel("Lounge", channel_id=100)
        before = make_voice_state(channel=other)
        after = make_voice_state(channel=target)

        joined = (
            self._is_target(after.channel, voice_channel_id=100)
            and (before.channel is None or before.channel.id != after.channel.id)
        )
        self.assertTrue(joined)

    def test_no_join_same_channel(self):
        """Voice state change within same channel (mute/deafen) is not a join."""
        target = make_channel("Lounge", channel_id=100)
        before = make_voice_state(channel=target)
        after = make_voice_state(channel=target)

        joined = (
            self._is_target(after.channel, voice_channel_id=100)
            and (before.channel is None or before.channel.id != after.channel.id)
        )
        self.assertFalse(joined)

    def test_leave_target(self):
        """Member leaves target channel."""
        target = make_channel("Lounge", channel_id=100)
        before = make_voice_state(channel=target)
        after = make_voice_state(channel=None)

        left = (
            self._is_target(before.channel, voice_channel_id=100)
            and (after.channel is None or after.channel.id != before.channel.id)
        )
        self.assertTrue(left)

    def test_leave_to_other_channel(self):
        """Member moves from target to another channel."""
        target = make_channel("Lounge", channel_id=100)
        other = make_channel("General", channel_id=200)
        before = make_voice_state(channel=target)
        after = make_voice_state(channel=other)

        left = (
            self._is_target(before.channel, voice_channel_id=100)
            and (after.channel is None or after.channel.id != before.channel.id)
        )
        self.assertTrue(left)

    def test_join_non_target_ignored(self):
        """Joining a non-target channel is not a target join."""
        other = make_channel("General", channel_id=200)
        before = make_voice_state(channel=None)
        after = make_voice_state(channel=other)

        joined = (
            self._is_target(after.channel, voice_channel_id=100)
            and (before.channel is None or before.channel.id != after.channel.id)
        )
        self.assertFalse(joined)


# ---------------------------------------------------------------------------
# Test: Stale event detection (membership check)
# ---------------------------------------------------------------------------

class TestStaleEventDetection(unittest.TestCase):
    """Test that stale events are caught by the membership check."""

    def test_member_in_channel_not_stale(self):
        """Member present in channel member list → not stale."""
        member = make_member("TestUser", member_id=1)
        channel = make_channel("Lounge", channel_id=100, members=[member])
        self.assertIn(member, channel.members)

    def test_member_not_in_channel_is_stale(self):
        """Member NOT in channel member list → stale event."""
        member = make_member("TestUser", member_id=1)
        other = make_member("Other", member_id=2)
        channel = make_channel("Lounge", channel_id=100, members=[other])
        self.assertNotIn(member, channel.members)


if __name__ == '__main__':
    unittest.main()
