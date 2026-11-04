import gzip
import io
import struct
import unittest

from PIL import Image

from jellysports.util import embedcenter as ec


def make_ts(packets=4):
    pkt = b"\x47\x40\x00\x10" + b"\x00" * 184
    return pkt * packets


def make_png(ts, magic=b"TIKTIKPX", declared=None):
    body = gzip.compress(ts)
    payload = magic + struct.pack(">I", len(body) if declared is None else declared) + body
    width = 64
    payload += b"\x00" * (-len(payload) % (width * 3))
    height = len(payload) // (width * 3)
    img = Image.frombytes("RGB", (width, height), payload)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def make_index(entries, target=4, stream_id="a" * 32, epoch="1"):
    return {"schema_version": 1, "stream_id": stream_id, "epoch": epoch, "target_duration": target,
            "segments": entries}


def seg(sn, cc=0, dur=4.0, pts=1):
    return {"id": f"x-{sn}.ts", "sn": sn, "cc": cc, "duration": dur, "pts": pts, "url": f"https://cdn.example/{sn}.png"}


class DecodeSegmentTests(unittest.TestCase):
    def test_round_trip(self):
        ts = make_ts(10)
        self.assertEqual(ec.decode_segment(make_png(ts)), ts)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            ec.decode_segment(make_png(make_ts(), magic=b"NOTMAGIC"))

    def test_length_beyond_pixels(self):
        with self.assertRaises(ValueError):
            ec.decode_segment(make_png(make_ts(), declared=10_000_000))

    def test_not_transport_stream(self):
        with self.assertRaises(ValueError):
            ec.decode_segment(make_png(b"\x00" * 376))

    def test_partial_packet_rejected(self):
        with self.assertRaises(ValueError):
            ec.decode_segment(make_png(make_ts(4) + b"\x47"))

    def test_oversize_png_rejected(self):
        with self.assertRaises(ValueError):
            ec.decode_segment(b"\x00" * (ec.MAX_PNG + 1))


class ParseIndexTests(unittest.TestCase):
    def test_valid(self):
        idx = ec.parse_index(make_index([seg(1), seg(2)]))
        self.assertEqual([e["sn"] for e in idx["entries"]], [1, 2])
        self.assertEqual(idx["target"], 4)

    def test_segments_without_clock_are_dropped(self):
        idx = ec.parse_index(make_index([seg(1), dict(seg(2), pts=None)]))
        self.assertEqual([e["sn"] for e in idx["entries"]], [1])

    def test_rejects_bad_schema(self):
        bad = make_index([seg(1)])
        bad["schema_version"] = 2
        with self.assertRaises(ec.ChannelError):
            ec.parse_index(bad)

    def test_rejects_non_https_segment(self):
        with self.assertRaises(ec.ChannelError):
            ec.parse_index(make_index([dict(seg(1), url="http://cdn.example/1.png")]))

    def test_rejects_path_traversal_id(self):
        with self.assertRaises(ec.ChannelError):
            ec.parse_index(make_index([dict(seg(1), id="../etc/passwd")]))


class BuildPlaylistTests(unittest.TestCase):
    def uri(self, sid):
        return f"/seg/{sid}"

    def test_contiguous(self):
        text = ec.build_playlist(ec.parse_index(make_index([seg(10), seg(11), seg(12)])), self.uri)
        lines = text.splitlines()
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:10", lines)
        self.assertIn("#EXT-X-DISCONTINUITY-SEQUENCE:0", lines)
        self.assertEqual([l for l in lines if l.startswith("/seg/")], ["/seg/x-10.ts", "/seg/x-11.ts", "/seg/x-12.ts"])
        self.assertNotIn("#EXT-X-DISCONTINUITY", lines)

    def test_discontinuity_marked(self):
        idx = ec.parse_index(make_index([seg(1, cc=3), seg(2, cc=3), seg(3, cc=4)]))
        lines = ec.build_playlist(idx, self.uri).splitlines()
        self.assertIn("#EXT-X-DISCONTINUITY-SEQUENCE:3", lines)
        self.assertEqual(lines.index("#EXT-X-DISCONTINUITY") + 2, lines.index("/seg/x-3.ts"))

    def test_gap_rejected(self):
        idx = ec.parse_index(make_index([seg(1), seg(2), seg(4)]))
        with self.assertRaises(ec.PlaylistUnavailable):
            ec.build_playlist(idx, self.uri)

    def test_short_window_rejected(self):
        idx = ec.parse_index(make_index([seg(1), seg(2)]))
        with self.assertRaises(ec.PlaylistUnavailable):
            ec.build_playlist(idx, self.uri)

    def test_discontinuity_jump_rejected(self):
        idx = ec.parse_index(make_index([seg(1, cc=0), seg(2, cc=2), seg(3, cc=2)]))
        with self.assertRaises(ec.PlaylistUnavailable):
            ec.build_playlist(idx, self.uri)


class EmbedPageTests(unittest.TestCase):
    def test_player_frame_extracted(self):
        html = '<iframe src="//embedcenter.st/embed/hls_co.php?stream=dazhfiach15" style="width:100%"></iframe>'
        self.assertEqual(ec.IFRAME_RE.search(html).group(1), "/embed/hls_co.php?stream=dazhfiach15")

    def test_embed_url_validation(self):
        ec.Channel("https://streamec.st/embed/ch5.php")
        with self.assertRaises(ValueError):
            ec.Channel("https://evil.example/embed/ch5.php")


if __name__ == "__main__":
    unittest.main()
