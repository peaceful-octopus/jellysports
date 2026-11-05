import argparse
import datetime
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from jellysports.jellysports import Collector, build_parser
from jellysports.util.models import Event


NOW = datetime.datetime(2026, 11, 5, 18, tzinfo=datetime.timezone.utc)


class _Proxy:
    def stream_url(self, key): return f"http://x/stream/{key}.m3u8"
    def image_url(self, path): return f"http://x/images/{os.path.basename(path)}"


def _collector(out, number):
    args = build_parser().parse_args(["-o", out] + (["-n", str(number)] if number is not None else []))
    c = Collector(args, _Proxy(), None)
    base = NOW
    for i, key in enumerate(("bbb", "aaa")):
        c.events[key] = Event(key=key, title=f"T{i}", sport="Soccer", league="", kickoff=base + datetime.timedelta(hours=i),
                              embed_url="https://streamec.st/embed/ch1.php", ready=True)
    return c


class NumberingTests(unittest.TestCase):
    def test_numbers_written(self):
        with tempfile.TemporaryDirectory() as out:
            c = _collector(out, 42)
            c.write(NOW)
            m3u = open(os.path.join(c.docs, "jellysports.m3u"), encoding="utf-8").read()
            self.assertIn('tvg-chno="42.1"', m3u)
            self.assertIn('tvg-chno="42.2"', m3u)
            names = [d.text for d in ET.parse(os.path.join(c.docs, "jellysports.xml")).getroot().iter("display-name")]
            self.assertEqual(names, ["T0", "42.1", "T1", "42.2"])

    def test_no_numbers_by_default(self):
        with tempfile.TemporaryDirectory() as out:
            c = _collector(out, None)
            c.write(NOW)
            self.assertNotIn("tvg-chno", open(os.path.join(c.docs, "jellysports.m3u"), encoding="utf-8").read())


class ListedTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as out:
            self.c = _collector(out, None)
        self.ev = self.c.events["bbb"]  # kicks off at NOW
        self.ev.ready = False

    def at(self, minutes):
        return NOW + datetime.timedelta(minutes=minutes)

    def test_upcoming_without_stream_is_listed(self):
        self.assertTrue(self.c._listed(self.ev, self.at(-120)))

    def test_beyond_horizon_not_listed(self):
        self.assertFalse(self.c._listed(self.ev, self.at(-25 * 60)))

    def test_never_live_dropped_after_window(self):
        self.assertTrue(self.c._listed(self.ev, self.at(14)))
        self.assertFalse(self.c._listed(self.ev, self.at(16)))

    def test_live_stays_listed_after_window(self):
        self.ev.ready = self.ev.was_live = True
        self.assertTrue(self.c._listed(self.ev, self.at(120)))

    def test_off_air_after_live_dropped(self):
        self.ev.was_live = True
        self.assertFalse(self.c._listed(self.ev, self.at(-10)))

    def test_needs_write_tracks_listed_set(self):
        with tempfile.TemporaryDirectory() as out:
            c = _collector(out, None)
            for ev in c.events.values():
                ev.ready = False
            self.assertTrue(c.needs_write(NOW))
            c.write(NOW)
            self.assertFalse(c.needs_write(NOW))
            self.assertTrue(c.needs_write(NOW + datetime.timedelta(hours=10)))


if __name__ == "__main__":
    unittest.main()
