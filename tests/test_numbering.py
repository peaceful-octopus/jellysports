import argparse
import datetime
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from jellysports.jellysports import Collector, build_parser
from jellysports.util.models import Event


class _Proxy:
    def stream_url(self, key): return f"http://x/stream/{key}.m3u8"
    def image_url(self, path): return f"http://x/images/{os.path.basename(path)}"


def _collector(out, number):
    args = build_parser().parse_args(["-o", out] + (["-n", str(number)] if number is not None else []))
    c = Collector(args, _Proxy(), None)
    base = datetime.datetime(2026, 11, 5, 18, tzinfo=datetime.timezone.utc)
    for i, key in enumerate(("bbb", "aaa")):
        c.events[key] = Event(key=key, title=f"T{i}", sport="Soccer", league="", kickoff=base + datetime.timedelta(hours=i),
                              embed_url="https://streamec.st/embed/ch1.php", ready=True)
    return c


class NumberingTests(unittest.TestCase):
    def test_numbers_written(self):
        with tempfile.TemporaryDirectory() as out:
            c = _collector(out, 42)
            c.write()
            m3u = open(os.path.join(c.docs, "jellysports.m3u"), encoding="utf-8").read()
            self.assertIn('tvg-chno="42.1"', m3u)
            self.assertIn('tvg-chno="42.2"', m3u)
            names = [d.text for d in ET.parse(os.path.join(c.docs, "jellysports.xml")).getroot().iter("display-name")]
            self.assertEqual(names, ["T0", "42.1", "T1", "42.2"])

    def test_no_numbers_by_default(self):
        with tempfile.TemporaryDirectory() as out:
            c = _collector(out, None)
            c.write()
            self.assertNotIn("tvg-chno", open(os.path.join(c.docs, "jellysports.m3u"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
