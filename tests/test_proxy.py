import socket
import unittest
from unittest import mock
import urllib.error
import urllib.request

from sportyfin.util import embedcenter as ec
from sportyfin.util import proxy as proxy_mod
from tests.test_embedcenter import make_index, make_png, make_ts, seg


class FakeChannel:
    def __init__(self, index=None, error=None):
        self._index, self._error = index, error
        self.urls = {e["id"]: e["url"] for e in (index or {}).get("entries", [])}

    def playlist(self, segment_uri):
        if self._error:
            raise self._error
        return ec.build_playlist(self._index, segment_uri)

    def segment_url(self, segment_id):
        return self.urls.get(segment_id)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.headers, e.read()


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proxy = proxy_mod.StreamProxy("127.0.0.1", self.port, self.base)
        self.proxy.start()
        self.addCleanup(self.proxy.stop)
        self.index = ec.parse_index(make_index([seg(1), seg(2), seg(3)]))

    def test_playlist_points_at_proxy_segments(self):
        self.proxy.register("abc123", FakeChannel(self.index))
        status, headers, body = get(f"{self.base}/stream/abc123.m3u8")
        self.assertEqual(status, 200)
        self.assertIn("mpegurl", headers["Content-Type"])
        self.assertIn(f"{self.base}/seg/abc123/x-1.ts", body.decode())

    def test_not_live_is_404(self):
        self.proxy.register("abc123", FakeChannel(error=ec.NotLive("no")))
        self.assertEqual(get(f"{self.base}/stream/abc123.m3u8")[0], 404)

    def test_unavailable_is_503(self):
        self.proxy.register("abc123", FakeChannel(error=ec.PlaylistUnavailable("gap")))
        self.assertEqual(get(f"{self.base}/stream/abc123.m3u8")[0], 503)

    def test_unknown_and_malformed_keys(self):
        self.assertEqual(get(f"{self.base}/stream/nope.m3u8")[0], 404)
        self.assertEqual(get(f"{self.base}/stream/..%2f..%2fetc.m3u8")[0], 404)
        self.assertEqual(get(f"{self.base}/other")[0], 404)

    def test_segment_is_decoded_to_ts_and_cached(self):
        ts = make_ts(6)
        png = make_png(ts)
        self.proxy.register("abc123", FakeChannel(self.index))
        with mock.patch.object(proxy_mod, "download_segment", return_value=png) as dl:
            first = get(f"{self.base}/seg/abc123/x-2.ts")
            second = get(f"{self.base}/seg/abc123/x-2.ts")
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1]["Content-Type"], "video/mp2t")
        self.assertEqual(first[2], ts)
        self.assertEqual(second[2], ts)
        self.assertEqual(dl.call_count, 1)

    def test_expired_segment_is_404(self):
        self.proxy.register("abc123", FakeChannel(self.index))
        self.assertEqual(get(f"{self.base}/seg/abc123/gone.ts")[0], 404)

    def test_bad_segment_is_502(self):
        self.proxy.register("abc123", FakeChannel(self.index))
        with mock.patch.object(proxy_mod, "download_segment", return_value=b"not a png"):
            self.assertEqual(get(f"{self.base}/seg/abc123/x-1.ts")[0], 502)


if __name__ == "__main__":
    unittest.main()
