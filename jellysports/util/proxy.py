"""
Local HLS proxy for embedcenter streams. Jellyfin/ffmpeg play http://<host>:<port>/stream/<key>.m3u8; the proxy
builds the playlist from the CDN's segment index and serves each image segment decoded to MPEG-TS.

No browser is involved. Upstream is only contacted while a client is requesting.
"""
import collections
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional
from urllib.parse import quote

import requests

from .embedcenter import ChannelError, Channel, NotLive, USER_AGENT, MAX_PNG, decode_segment
from .pretty_print import *

SEGMENT_CACHE_SIZE = 8
KEY_CHARS = set("0123456789abcdef")


class SegmentCache:
    """Small LRU of decoded segments. Concurrent requests for the same segment share one download+decode."""

    def __init__(self, size: int = SEGMENT_CACHE_SIZE):
        self._size = size
        self._data: "collections.OrderedDict[tuple, bytes]" = collections.OrderedDict()
        self._locks: Dict[tuple, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: tuple, loader) -> bytes:
        with self._guard:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                if key in self._data:
                    return self._data[key]
            value = loader()
            with self._guard:
                self._data[key] = value
                while len(self._data) > self._size:
                    self._data.popitem(last=False)
                self._locks.pop(key, None)
            return value


def download_segment(url: str, session: requests.Session) -> bytes:
    resp = session.get(url, timeout=(5, 20), stream=True)
    resp.raise_for_status()
    data = resp.raw.read(MAX_PNG + 1, decode_content=True)
    if len(data) > MAX_PNG:
        raise ValueError("Segment image too large")
    return data


class _Handler(BaseHTTPRequestHandler):
    server_version = "jellysports-proxy"

    def log_message(self, fmt, *args):
        pind2(fmt % args, colours.OKCYAN, otype.DEBUG)

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain", head: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def _route(self, head: bool):
        path = self.path.split("?", 1)[0]
        parts = path.strip("/").split("/")
        try:
            if len(parts) == 2 and parts[0] == "stream" and parts[1].endswith(".m3u8"):
                return self._playlist(parts[1][:-5], head)
            if len(parts) == 3 and parts[0] == "seg":
                return self._segment(parts[1], parts[2], head)
        except (BrokenPipeError, ConnectionResetError):
            return
        self._send(404, b"Not found\n", head=head)

    def _channel(self, key: str) -> Optional[Channel]:
        return self.server.channels.get(key) if set(key) <= KEY_CHARS else None

    def _playlist(self, key: str, head: bool):
        channel = self._channel(key)
        if channel is None:
            return self._send(404, b"Unknown stream\n", head=head)
        base = self.server.public_url
        try:
            text = channel.playlist(lambda sid: f"{base}/seg/{key}/{quote(sid, safe='%')}")
        except NotLive:
            return self._send(404, b"Not live\n", head=head)
        except ChannelError as e:
            p(f"Playlist unavailable for {key}: {e}", colours.WARNING, otype.DEBUG)
            return self._send(503, b"Playlist unavailable\n", head=head)
        self._send(200, text.encode(), "application/vnd.apple.mpegurl", head)

    def _segment(self, key: str, segment_id: str, head: bool):
        channel = self._channel(key)
        if channel is None:
            return self._send(404, b"Unknown stream\n", head=head)
        url = channel.segment_url(segment_id)
        if url is None:
            return self._send(404, b"Segment expired\n", head=head)
        try:
            ts = self.server.segments.get(
                (key, segment_id),
                lambda: decode_segment(download_segment(url, self.server.session)),
            )
        except (requests.RequestException, ValueError, OSError) as e:
            p(f"Segment {segment_id} failed: {e}", colours.WARNING, otype.DEBUG)
            return self._send(502, b"Segment unavailable\n", head=head)
        self._send(200, ts, "video/mp2t", head)


class StreamProxy:
    def __init__(self, host: str, port: int, public_url: str):
        self.public_url = public_url.rstrip("/")
        self._server = ThreadingHTTPServer((host, port), _Handler)
        self._server.daemon_threads = True
        self._server.channels = {}
        self._server.segments = SegmentCache()
        self._server.public_url = self.public_url
        self._server.session = requests.Session()
        self._server.session.headers["User-Agent"] = USER_AGENT
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def register(self, key: str, channel: Channel) -> str:
        """Serve a channel and return the playlist URL for players."""
        self._server.channels[key] = channel
        return self.stream_url(key)

    def stream_url(self, key: str) -> str:
        return f"{self.public_url}/stream/{key}.m3u8"
