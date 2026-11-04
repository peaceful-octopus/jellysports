"""Team badge cache: each badge URL is downloaded once and kept on disk."""
import datetime
import hashlib
import io
import json
import os
import threading
from typing import Optional

import requests
from PIL import Image

from .pretty_print import *

RETRY_FAILED_AFTER = datetime.timedelta(hours=6)
MAX_BYTES = 5_000_000
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class LogoCache:
    def __init__(self, directory: str):
        self.directory = directory
        self.index_path = os.path.join(directory, "index.json")
        self._lock = threading.Lock()
        self._index = {}
        try:
            with open(self.index_path, encoding="utf-8") as f:
                self._index = json.load(f)
        except (OSError, ValueError):
            pass

    def _save(self):
        os.makedirs(self.directory, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=1)
        os.replace(tmp, self.index_path)

    def get(self, url: Optional[str]) -> Optional[str]:
        """Path of the cached PNG for a badge URL, downloading it the first time. None if unavailable."""
        if not url:
            return None
        key = hashlib.sha1(url.encode()).hexdigest()
        path = os.path.join(self.directory, f"{key}.png")
        with self._lock:
            if os.path.isfile(path):
                return path
            failed = self._index.get(key)
            if failed:
                age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(failed["failed_at"])
                if age < RETRY_FAILED_AFTER:
                    return None
            try:
                self._download(url, path)
            except (requests.RequestException, OSError, ValueError) as e:
                p(f"Could not download logo {url}", colours.FAIL, otype.DEBUG, e)
                self._index[key] = {"url": url, "failed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
                self._save()
                return None
            if key in self._index:
                del self._index[key]
                self._save()
            pind2(f"Cached logo {url}", colours.OKCYAN, otype.DEBUG)
            return path

    @staticmethod
    def _download(url: str, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, stream=True)
        resp.raise_for_status()
        data = resp.raw.read(MAX_BYTES + 1, decode_content=True)
        if len(data) > MAX_BYTES:
            raise ValueError("Logo too large")
        img = Image.open(io.BytesIO(data))
        img.load()
        tmp = path + ".tmp"
        img.convert("RGBA").save(tmp, format="PNG")
        os.replace(tmp, path)
