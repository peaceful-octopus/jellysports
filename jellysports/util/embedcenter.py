"""
Client for the embedcenter.st delivery chain behind streamec.st embeds. No browser is involved.

    embed page  -> iframe hls_co.php?stream=<name>
    &grant=1    -> URL of a JSON segment index on the CDN
    index JSON  -> segments {id, sn, cc, duration, pts, url}, refreshed about every 2 s
    segment URL -> PNG whose pixels hold "TIKTIKPX" + u32 length + gzip(MPEG-TS)
"""
import collections
import io
import re
import struct
import threading
import time
import zlib
from typing import Optional
from urllib.parse import urlsplit

import requests
from PIL import Image

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
EMBED_ORIGIN = "https://embedcenter.st"
EMBED_REFERER = "https://streamec.st/"
TIMEOUT = (5, 15)

MAGIC = b"TIKTIKPX"
MAX_PNG = 10_240_000
MAX_TS = 8_388_560
GRANT_TTL = 2.5 * 3600   # the site's own player renews its grant after ~3 h
INDEX_TTL = 2.0          # seconds a fetched index is reused
RECENT_SEGMENTS = 32

IFRAME_RE = re.compile(r"""src=["'](?:https?:)?//embedcenter\.st(/embed/hls_co\.php\?stream=[\w-]+)["']""")
SEGMENT_ID_RE = re.compile(r"^(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+$")


class ChannelError(Exception):
    """The channel could not be resolved or returned something unusable."""


class NotLive(ChannelError):
    """The channel exists but is not broadcasting (index 404)."""


class PlaylistUnavailable(ChannelError):
    """The current index cannot produce a safe playlist yet."""


def decode_segment(png: bytes) -> bytes:
    """Turn a CDN image segment into MPEG-TS bytes."""
    if len(png) > MAX_PNG:
        raise ValueError("Segment image too large")
    img = Image.open(io.BytesIO(png))
    img.load()
    pixels = img.convert("RGB").tobytes()
    if pixels[:8] != MAGIC:
        raise ValueError("Unexpected segment header")
    (length,) = struct.unpack(">I", pixels[8:12])
    if not 0 < length <= len(pixels) - 12:
        raise ValueError("Bad segment length")
    inflater = zlib.decompressobj(31)
    ts = inflater.decompress(pixels[12:12 + length], MAX_TS + 1)
    if len(ts) > MAX_TS:
        raise ValueError("Decoded segment too large")
    if len(ts) < 376 or len(ts) % 188 or ts[0::188] != b"\x47" * (len(ts) // 188):
        raise ValueError("Decoded data is not MPEG-TS")
    return ts


def parse_index(value: dict) -> dict:
    """Validate the CDN index the same way the site's own player does; drops segments without a clock."""
    if (value.get("schema_version") != 1
            or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("stream_id", "")))
            or not re.fullmatch(r"[0-9]{1,20}", str(value.get("epoch", "")))
            or not isinstance(value.get("target_duration"), int)
            or not 1 <= value["target_duration"] <= 30
            or not isinstance(value.get("segments"), list)
            or not 1 <= len(value["segments"]) <= 128):
        raise ChannelError("Invalid CDN index")
    entries, seen = [], set()
    for e in value["segments"]:
        sid = e.get("id")
        if (not isinstance(sid, str) or len(sid) > 768 or not SEGMENT_ID_RE.match(sid)
                or not isinstance(e.get("duration"), (int, float)) or not 0 < e["duration"] <= 30
                or not isinstance(e.get("sn"), int) or e["sn"] < 0
                or not isinstance(e.get("cc"), int) or e["cc"] < 0):
            raise ChannelError("Invalid segment metadata")
        if e.get("pts") is None or sid in seen:
            continue
        if urlsplit(str(e.get("url", ""))).scheme != "https":
            raise ChannelError("Unsupported segment URL")
        seen.add(sid)
        entries.append({k: e[k] for k in ("id", "sn", "cc", "duration", "pts", "url")})
    if not entries:
        raise ChannelError("Index has no usable segments")
    return {"epoch": f"{value['stream_id']}:{value['epoch']}", "target": value["target_duration"], "entries": entries}


def build_playlist(index: dict, segment_uri) -> str:
    """HLS playlist from a parsed index. segment_uri(id) gives the URI a player should request."""
    entries, target = index["entries"], index["target"]
    if sum(e["duration"] for e in entries) < 3 * target:
        raise PlaylistUnavailable("Window shorter than three target durations")
    for prev, cur in zip(entries, entries[1:]):
        if cur["sn"] != prev["sn"] + 1 or not prev["cc"] <= cur["cc"] <= prev["cc"] + 1:
            raise PlaylistUnavailable("Index is not contiguous")
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}",
             f"#EXT-X-MEDIA-SEQUENCE:{entries[0]['sn']}", f"#EXT-X-DISCONTINUITY-SEQUENCE:{entries[0]['cc']}"]
    for i, e in enumerate(entries):
        if i and e["cc"] != entries[i - 1]["cc"]:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{e['duration']:.3f},")
        lines.append(segment_uri(e["id"]))
    return "\n".join(lines) + "\n"


class Channel:
    """One streamec.st embed. Thread-safe: many clients share one upstream index poll."""

    def __init__(self, embed_url: str, session: Optional[requests.Session] = None):
        parts = urlsplit(embed_url)
        if parts.hostname not in ("streamec.st", "embedcenter.st") or not parts.path.startswith("/embed/"):
            raise ValueError(f"Not an embedcenter embed URL: {embed_url}")
        self.page_url = f"{EMBED_ORIGIN}{parts.path}"
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._lock = threading.Lock()
        self._index_url: Optional[str] = None
        self._granted_at = 0.0
        self._index: Optional[dict] = None
        self._index_at = 0.0
        self._recent: "collections.OrderedDict[str, str]" = collections.OrderedDict()

    def _grant(self):
        page = self._session.get(self.page_url, headers={"Referer": EMBED_REFERER}, timeout=TIMEOUT)
        if page.status_code == 404:
            raise ChannelError("Embed page not found")
        page.raise_for_status()
        m = IFRAME_RE.search(page.text)
        if not m:
            raise ChannelError("Player frame not found in embed page")
        grant = self._session.get(f"{EMBED_ORIGIN}{m.group(1)}&grant=1", headers={"Referer": self.page_url}, timeout=TIMEOUT)
        if grant.status_code != 200:
            raise ChannelError(f"Grant refused ({grant.status_code})")
        url = grant.json().get("url", "")
        if urlsplit(url).scheme != "https":
            raise ChannelError("Grant returned no usable URL")
        self._index_url, self._granted_at = url, time.monotonic()

    def _fetch_index(self) -> dict:
        for attempt in (1, 2):
            if not self._index_url or time.monotonic() - self._granted_at > GRANT_TTL:
                self._grant()
            resp = self._session.get(self._index_url, headers={"Referer": EMBED_ORIGIN + "/"}, timeout=TIMEOUT)
            if resp.status_code == 200:
                return parse_index(resp.json())
            if resp.status_code == 404:
                raise NotLive("Channel is not live")
            if resp.status_code in (401, 403) and attempt == 1:
                self._index_url = None  # grant expired or revoked: get a new one once
                continue
            raise ChannelError(f"Index request failed ({resp.status_code})")
        raise ChannelError("Index request failed")

    def index(self, max_age: float = INDEX_TTL) -> dict:
        """Current parsed index, reusing a fetch younger than max_age seconds."""
        with self._lock:
            if self._index is not None and time.monotonic() - self._index_at < max_age:
                return self._index
            try:
                index = self._fetch_index()
            except requests.RequestException as e:
                raise ChannelError(f"Network error: {e}") from e
            except ValueError as e:
                raise ChannelError(f"Bad response: {e}") from e
            self._index, self._index_at = index, time.monotonic()
            for e in index["entries"]:
                self._recent[e["id"]] = e["url"]
                self._recent.move_to_end(e["id"])
            while len(self._recent) > RECENT_SEGMENTS:
                self._recent.popitem(last=False)
            return index

    def segment_url(self, segment_id: str) -> Optional[str]:
        with self._lock:
            return self._recent.get(segment_id)

    def playlist(self, segment_uri) -> str:
        return build_playlist(self.index(), segment_uri)
