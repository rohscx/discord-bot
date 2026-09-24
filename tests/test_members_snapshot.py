import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from presence_snapshot import build_members_snapshot, write_payload, read_snapshot

def member(mid, name, status="online"):
    return NS(id=mid, name=name, display_name=name.title(), status=status,
              activities=[NS(type=NS(value=0), name="Test Game"),
                          NS(type=NS(value=4), name="private status")])

class MembersSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "members.json"
        self.guilds = [NS(id=1, members=[member(10, "merda"), member(20, "excluded")]),
                       NS(id=2, members=[member(10, "merda", "idle"), member(30, "other", "offline")]),
                       NS(id=3, unavailable=True)]
    def publish(self, connected=True):
        payload = build_members_snapshot(self.guilds, connected, {20})
        write_payload(self.path, payload)
        return payload
    def test_all_guilds_exclusions_and_private_games(self):
        self.publish()
        result = read_snapshot(self.path)
        self.assertTrue(result["available"])
        self.assertEqual(len(result["members"]), 3)
        self.assertEqual(result["unavailable_guild_ids"], ["3"])
        self.assertNotIn("private status", self.path.read_text())
        self.assertNotIn("excluded", self.path.read_text())
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(result["members"][0]["activities"], [{"type":"playing","name":"Test Game"}])
    def test_name_id_and_guild_lookup_preserves_ambiguity(self):
        self.publish()
        self.assertEqual(len(read_snapshot(self.path, member="MERDA")["members"]), 2)
        result = read_snapshot(self.path, member="10", guild_id=2)
        self.assertEqual(result["members"][0]["status"], "idle")
        self.assertEqual(len(result["members"]), 1)
        self.assertFalse(read_snapshot(self.path, member="missing")["available"])
        self.assertFalse(read_snapshot(self.path, guild_id=3)["available"])
    def test_disconnect_clears_data(self):
        self.publish()
        self.publish(False)
        self.assertEqual(json.loads(self.path.read_text())["members"], [])
        self.assertFalse(read_snapshot(self.path)["available"])
    def test_stale_future_and_malformed_rejected(self):
        original = self.publish()
        for change in ({"checked_at":time.time()-120}, {"checked_at":time.time()+120},
                       {"members":[{}]}, {"members":None}):
            write_payload(self.path, dict(original, **change))
            self.assertFalse(read_snapshot(self.path)["available"])
    def test_member_removal_disappears_on_refresh(self):
        self.publish()
        self.guilds[0].members = []
        self.guilds[1].members = []
        self.publish()
        self.assertEqual(read_snapshot(self.path)["members"], [])
