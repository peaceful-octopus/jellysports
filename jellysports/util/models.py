import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class Event:
    key: str                      # stable id used in output files and proxy URLs
    title: str
    sport: str                    # e.g. "Basketball"
    league: str                   # e.g. "nba", "uefa-champions"; may be empty
    kickoff: datetime.datetime    # timezone-aware UTC
    embed_url: str                # https://streamec.st/embed/chN.php
    home: Optional[str] = None
    away: Optional[str] = None
    home_badge: Optional[str] = None
    away_badge: Optional[str] = None
    live: bool = False            # the site's own live flag
    ready: bool = False           # a working stream was confirmed
    attempts: int = 0
    was_live: bool = False        # a stream has been confirmed at some point
    image_tried: bool = False
    checked_at: datetime.datetime = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    image: Optional[str] = None
