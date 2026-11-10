"""Unit tests for idle_gate.decide (no Hermes, no real state files).

Run: python tests/test_gate.py
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import idle_gate  # noqa: E402
import topics  # noqa: E402

H = 3600


def ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


class GateTest(unittest.TestCase):
    def run_gate(self, now, state=None, last_user=None, force=False):
        st = topics._empty_state()
        st.update(state or {})
        with mock.patch.object(topics, "load_state", return_value=st), \
             mock.patch.object(idle_gate, "last_user_message_at", return_value=last_user), \
             mock.patch.object(topics, "suggest_topic", return_value="food"):
            return idle_gate.decide("friend", datetime.fromisoformat(now), force)

    def test_first_ever_opener_in_window(self):
        d, msg, st = self.run_gate("2026-11-10T10:00")
        self.assertEqual(d, "opener")
        self.assertIn("[AIEnglish opener request]", msg)
        self.assertIn("💬 Jake:", msg)
        self.assertEqual(len(st["openers"]), 1)

    def test_outside_window_evening(self):
        d, msg, _ = self.run_gate("2026-11-10T19:00")
        self.assertEqual(d, "outside-window")
        self.assertIsNone(msg)

    def test_window_end_is_exclusive(self):
        self.assertEqual(self.run_gate("2026-11-10T18:00")[0], "outside-window")
        self.assertEqual(self.run_gate("2026-11-10T07:59")[0], "outside-window")
        self.assertEqual(self.run_gate("2026-11-10T08:00")[0], "opener")

    def test_idle_too_short_after_topic_end(self):
        d, _, _ = self.run_gate("2026-11-10T12:00", {"last_end_at": ts("2026-11-10T10:00")},
                                last_user=ts("2026-11-10T09:59"))
        self.assertTrue(d.startswith("idle-too-short"))

    def test_opener_after_3h_idle(self):
        d, _, _ = self.run_gate("2026-11-10T13:01", {"last_end_at": ts("2026-11-10T10:00")},
                                last_user=ts("2026-11-10T09:59"))
        self.assertEqual(d, "opener")

    def test_daily_limit(self):
        openers = [ts("2026-11-10T08:30"), ts("2026-11-10T12:00")]
        d, _, _ = self.run_gate("2026-11-10T17:00",
                                {"openers": openers, "last_end_at": ts("2026-11-10T13:00")},
                                last_user=ts("2026-11-10T12:30"))
        self.assertTrue(d.startswith("daily-limit"))

    def test_active_conversation_is_left_alone(self):
        d, msg, _ = self.run_gate("2026-11-10T12:00", {"last_end_at": ts("2026-11-10T08:00")},
                                  last_user=ts("2026-11-10T11:50"))
        self.assertEqual(d, "active")
        self.assertIsNone(msg)

    def test_stale_topic_with_replies_requests_summary(self):
        d, msg, st = self.run_gate("2026-11-11T12:00", {"last_end_at": ts("2026-11-10T08:00"),
                                                        "openers": [ts("2026-11-10T09:00")]},
                                   last_user=ts("2026-11-10T10:00"))
        self.assertEqual(d, "stale-close-request")
        self.assertIn("[AIEnglish stale-close request]", msg)
        self.assertIn("stale_requested_at", st)

    def test_stale_request_not_repeated(self):
        d, msg, _ = self.run_gate("2026-11-11T12:30", {"last_end_at": ts("2026-11-10T08:00"),
                                                       "stale_requested_at": ts("2026-11-11T12:00")},
                                  last_user=ts("2026-11-10T10:00"))
        self.assertEqual(d, "stale-request-pending")
        self.assertIsNone(msg)

    def test_ignored_opener_closes_silently(self):
        d, msg, st = self.run_gate("2026-11-11T12:00", {"last_end_at": ts("2026-11-10T08:00"),
                                                        "openers": [ts("2026-11-10T10:00")]},
                                   last_user=ts("2026-11-10T07:00"))
        self.assertTrue(d.startswith("closed-silently"))
        self.assertIsNone(msg)
        self.assertGreater(st["last_end_at"], ts("2026-11-11T11:59"))

    def test_force_overrides_window(self):
        d, _, _ = self.run_gate("2026-11-10T22:00", force=True)
        self.assertEqual(d, "opener")


if __name__ == "__main__":
    unittest.main(verbosity=2)
