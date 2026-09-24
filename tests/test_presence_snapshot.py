import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from presence_snapshot import write_snapshot, read_snapshot


class SnapshotTests(unittest.TestCase):
    def test_private_games_only_and_disconnect_clears(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presence.json"
            member = NS(status="online", activities=[
                NS(type=NS(value=0), name="Test Game"),
                NS(type=NS(value=4), name="private custom status"),
                NS(type=NS(value=2), name="Spotify")])
            guild = NS(id=123, get_member=lambda member_id: member)
            write_snapshot(path, guild, 456, True)
            result = read_snapshot(path)
            self.assertTrue(result["available"])
            self.assertEqual(result["activities"], [{"type": "playing", "name": "Test Game"}])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            write_snapshot(path, guild, 456, False)
            self.assertFalse(read_snapshot(path)["available"])
            self.assertEqual(json.loads(path.read_text())["activities"], [])

    def test_stale_missing_excluded_and_no_game(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presence.json"
            self.assertFalse(read_snapshot(path)["available"])
            guild = NS(id=123, get_member=lambda _: NS(status="online", activities=[]))
            write_snapshot(path, guild, 456, True)
            self.assertEqual(read_snapshot(path)["activities"], [])
            with patch("presence_snapshot.time.time", return_value=time.time() + 120):
                self.assertFalse(read_snapshot(path)["available"])
            write_snapshot(path, guild, 456, True, excluded=True)
            self.assertFalse(read_snapshot(path)["available"])
            path.write_text("broken")
            self.assertFalse(read_snapshot(path)["available"])
