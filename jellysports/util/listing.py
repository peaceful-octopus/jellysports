"""
Event listing from gostreameast.one.

The site's JSON feeds are encrypted and decoded by the page's own script, so a headless Chrome loads the
page and asks it for the decoded matches (window.__lx(0)). Chrome is used for this listing only.
"""
import datetime
import hashlib
import os
import re
import shutil
from typing import List, Optional
from urllib.parse import urlsplit

from .models import Event

DEFAULT_SITE = "https://gostreameast.one"
LEAGUE_RE = re.compile(r"league-[a-z]+-(.+?)(?:-\d+)?$")
EMBED_HOSTS = ("streamec.st", "embedcenter.st")

_FETCH_JS = """
const done = arguments[arguments.length - 1];
window.__lx(0).then(d => done({ok: d}), e => done({error: String(e)}));
"""


class ListingError(Exception):
    pass


def _parse_time(value: str) -> datetime.datetime:
    dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _english_embed(streams: list) -> Optional[str]:
    for s in streams or []:
        url = s.get("embed_url") or ""
        if s.get("language") == "English" and urlsplit(url).hostname in EMBED_HOSTS:
            return url
    return None


def parse_matches(feed: dict) -> List[Event]:
    """Events that have an English embedcenter stream and are not finished."""
    events = []
    for m in feed.get("matches", []):
        if m.get("finished"):
            continue
        embed = _english_embed(m.get("streams"))
        if not embed or not m.get("starts_at") or m.get("id") is None:
            continue
        title = (m.get("title") or "").strip()
        home = (m.get("home") or {}).get("name")
        away = (m.get("away") or {}).get("name")
        if not (home and away):
            at = re.split(r"\s+at\s+", title, maxsplit=1)       # "Away at Home"
            vs = re.split(r"\s+vs\.?\s+", title, maxsplit=1)    # "Home vs Away"
            if len(at) == 2:
                away, home = away or at[0], home or at[1]
            elif len(vs) == 2:
                home, away = home or vs[0], away or vs[1]
        slug = LEAGUE_RE.search(m.get("api_id") or "")
        events.append(Event(
            key=hashlib.sha1(f"{m['id']}|{embed}".encode()).hexdigest()[:12],
            title=title or f"{away} at {home}",
            sport=m.get("sport_name") or m.get("sport") or "Sports",
            league=slug.group(1) if slug else "",
            kickoff=_parse_time(m["starts_at"]),
            embed_url=embed,
            home=home, away=away,
            home_badge=(m.get("home") or {}).get("badge"),
            away_badge=(m.get("away") or {}).get("badge"),
            live=bool(m.get("live")),
        ))
    return events


def matches_filter(event: Event, filters: List[str]) -> bool:
    """Case-insensitive substring match on sport, league slug and title; no filters matches everything."""
    if not filters:
        return True
    hay = f"{event.sport} {event.league} {event.title}".lower()
    return any(f.lower() in hay for f in filters)


class ListingClient:
    """Keeps one headless Chrome open; restarts it if it dies."""

    def __init__(self, site: str = DEFAULT_SITE):
        self.site = site
        self._driver = None

    def _start(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as e:
            raise ListingError("selenium is not installed (pip install selenium)") from e
        options = webdriver.ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1280,900"):
            options.add_argument(arg)
        # Use a browser/driver from CHROME_BIN / CHROMEDRIVER or PATH (e.g. Chromium in Docker);
        # otherwise Selenium locates Chrome and downloads a matching driver itself.
        binary = os.environ.get("CHROME_BIN") or next(
            (shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser") if shutil.which(n)), None)
        if binary:
            options.binary_location = binary
        driver_path = os.environ.get("CHROMEDRIVER") or shutil.which("chromedriver")
        try:
            service = webdriver.ChromeService(executable_path=driver_path) if driver_path else None
            driver = webdriver.Chrome(options=options, service=service)
        except Exception as e:
            raise ListingError(f"Could not start Chrome: {e}") from e
        try:
            driver.set_page_load_timeout(60)
            driver.set_script_timeout(30)
            driver.get(self.site)
            WebDriverWait(driver, 30).until(lambda d: d.execute_script("return typeof window.__lx === 'function'"))
        except Exception as e:
            driver.quit()
            raise ListingError(f"Could not load {self.site}: {e}") from e
        self._driver = driver

    def close(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    def fetch(self) -> List[Event]:
        last_error = None
        for _ in range(2):
            try:
                if self._driver is None:
                    self._start()
                result = self._driver.execute_async_script(_FETCH_JS)
                if "error" in result:
                    raise ListingError(result["error"])
                return parse_matches(result["ok"])
            except ListingError as e:
                last_error = e
                self.close()
            except Exception as e:  # browser crashed or page navigated away: restart once
                last_error = ListingError(str(e))
                self.close()
        raise last_error
