import argparse
import datetime
import os
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .util import game_info
from .util.embedcenter import Channel, ChannelError, NotLive
from .util.listing import DEFAULT_SITE, ListingClient, ListingError, matches_filter
from .util.logos import LogoCache
from .util.models import Event
from .util.pretty_print import *
from .util.proxy import StreamProxy

VERSION = "2.0.0"
UTC = datetime.timezone.utc

# Typical broadcast length used for the XMLTV programme end.
PROGRAMME_LENGTH = datetime.timedelta(hours=3)
# How long after kickoff an event stays in the output and is still looked for.
KEEP_AFTER_KICKOFF = datetime.timedelta(hours=5)
LISTING_REFRESH = datetime.timedelta(minutes=5)
# How often a channel already in the output is checked to still have a stream.
RECHECK_INTERVAL = datetime.timedelta(minutes=2)


def header():
    print()
    print(f"{colours.OKCYAN + colours.BOLD}JELLYSPORTS {VERSION}{colours.ENDC}")
    print(f"{colours.OKGREEN}Stream sports events straight from your Jellyfin server.")
    print(f"{colours.OKGREEN}Based on Sportyfin by Axel Mierczuk   Github: https://github.com/peaceful-octopus/jellysports{colours.ENDC}")
    print()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jellysports", description="Collect live sports streams into m3u/XMLTV files for Jellyfin.")
    ap.add_argument("command", nargs="?", choices=["run"], help="kept for compatibility with older invocations")
    ap.add_argument("-o", "--output", default=os.path.join(os.getcwd(), "output"), help="output directory (default ./output)")
    ap.add_argument("-l", "--league", action="append", default=[], metavar="TEXT",
                    help="only events whose sport, league or title contains TEXT (repeatable, case-insensitive), e.g. nba, hockey, champions")
    ap.add_argument("-a", "--all", action="store_true", help="all sports (default when no --league is given)")
    ap.add_argument("-d", "--once", action="store_true", help="check every matching event once, ignoring kickoff times, then exit")
    ap.add_argument("--lead", type=int, default=5, metavar="MIN", help="start checking an event this many minutes before kickoff (default 5)")
    ap.add_argument("--window", type=int, default=15, metavar="MIN", help="keep checking for this many minutes after kickoff (default 15)")
    ap.add_argument("--horizon", type=int, default=24, metavar="HOURS",
                    help="list events this many hours before kickoff, before their stream exists (default 24)")
    ap.add_argument("--interval", type=int, default=30, metavar="SEC", help="seconds between checks (default 30)")
    ap.add_argument("-n", "--channel-number", type=int, metavar="N",
                    help="major channel number; channels are numbered N.1, N.2, ... in kickoff order (default: no numbers)")
    ap.add_argument("--site", default=DEFAULT_SITE, help=f"listing site (default {DEFAULT_SITE})")
    ap.add_argument("--proxy-host", default="127.0.0.1", help="interface the stream proxy listens on (use 0.0.0.0 to serve other machines)")
    ap.add_argument("--proxy-port", type=int, default=8099)
    ap.add_argument("--public-url", help="base URL players use to reach the proxy (default http://localhost:<proxy-port>)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show debug output")
    ap.add_argument("-q", "--quiet", action="store_true", help="only show errors")
    return ap


class Collector:
    def __init__(self, args, proxy: StreamProxy, listing: ListingClient):
        self.args = args
        self.proxy = proxy
        self.listing = listing
        self.output = os.path.abspath(args.output)
        self.docs = os.path.join(self.output, "docs")
        self.images = os.path.join(self.output, "images")
        self.logos = LogoCache(os.path.join(self.output, "logos"))
        self.events: Dict[str, Event] = {}
        self.channels: Dict[str, Channel] = {}
        self.last_listing: Optional[datetime.datetime] = None
        self.written: Optional[tuple] = None  # keys of the channels in the files on disk

    def refresh_listing(self, now: datetime.datetime):
        p("COLLECTING EVENT LISTING", colours.HEADER, otype.REGULAR)
        try:
            found = [e for e in self.listing.fetch() if matches_filter(e, self.args.league)]
        except ListingError as e:
            p(f"Could not load the event listing: {e}", colours.FAIL, otype.ERROR)
            return
        self.last_listing = now
        for ev in found:
            known = self.events.get(ev.key)
            if known:
                known.kickoff, known.live = ev.kickoff, ev.live
                continue
            self.events[ev.key] = ev
            self.channels[ev.key] = Channel(ev.embed_url)
            self.proxy.register(ev.key, self.channels[ev.key])  # playable as soon as the stream starts
            p(f"Found - {ev.title} ({ev.sport}, {ev.kickoff.strftime('%Y-%m-%d %H:%M UTC')})", colours.OKGREEN, otype.REGULAR)
        if not found:
            p("No matching events listed", colours.WARNING, otype.REGULAR)

    def _due(self, ev: Event, now: datetime.datetime) -> bool:
        if ev.ready:
            # A channel that was playable can go off air; look again now and then.
            return not self.args.once and now - ev.checked_at >= RECHECK_INTERVAL
        if self.args.once:
            return True
        if now > ev.kickoff + KEEP_AFTER_KICKOFF:
            return False
        if ev.live:  # the site says it is on air
            return True
        return ev.kickoff - datetime.timedelta(minutes=self.args.lead) <= now <= ev.kickoff + datetime.timedelta(minutes=self.args.window)

    def poll(self, now: datetime.datetime):
        """Look for working streams on every event that is due."""
        for ev in self.events.values():
            if not self._due(ev, now):
                continue
            ev.attempts += 1
            ev.checked_at = now
            channel = self.channels[ev.key]
            p(f"Checking {ev.title}", colours.WARNING, otype.REGULAR)
            try:
                channel.index(max_age=0)
                channel.playlist(lambda sid: sid)  # the index must also yield a playable playlist
            except NotLive:
                pind2("Not live" if not ev.ready else "Stream went off air, removing channel", colours.WARNING, otype.DEBUG)
                ev.ready = False
                continue
            except ChannelError as e:
                pind2(f"Not available: {e}", colours.WARNING, otype.DEBUG)
                continue
            if ev.ready:
                continue
            ev.ready = ev.was_live = True
            pind2(f"Stream is live - {self.proxy.stream_url(ev.key)}", colours.OKGREEN, otype.REGULAR)
        # Forget events long after kickoff.
        expired = [k for k, e in self.events.items() if now > e.kickoff + KEEP_AFTER_KICKOFF]
        for key in expired:
            del self.events[key]
            self.channels.pop(key, None)

    def _image(self, ev: Event) -> Optional[str]:
        try:
            return game_info.generate_img(ev, self.logos, self.images)
        except Exception as e:
            p(f"Could not build image for {ev.title}", colours.FAIL, otype.ERROR, e)
            return None

    # Output ------------------------------------------------------------------------------------

    def _listed(self, ev: Event, now: datetime.datetime) -> bool:
        """Whether the event belongs in the output.

        Jellyfin refreshes its guide rarely, so an upcoming event is listed before its stream exists; the
        proxy serves it once the stream starts. An event that never came up within the window after kickoff,
        or that went off air after being live, is dropped.
        """
        if ev.ready:
            return True
        if self.args.once or ev.was_live:
            return False
        window = datetime.timedelta(minutes=self.args.window)
        return now - ev.kickoff <= window and ev.kickoff - now <= datetime.timedelta(hours=self.args.horizon)

    def listed(self, now: datetime.datetime) -> List[Event]:
        return sorted((e for e in self.events.values() if self._listed(e, now)), key=lambda e: (e.kickoff, e.title))

    def needs_write(self, now: datetime.datetime) -> bool:
        return self.written != tuple(e.key for e in self.listed(now))

    def write(self, now: datetime.datetime):
        os.makedirs(self.docs, exist_ok=True)
        live = self.listed(now)
        for ev in live:
            if ev.image is None and not ev.image_tried:
                ev.image_tried, ev.image = True, self._image(ev)
        p(f"Writing {len(live)} channel(s)", colours.HEADER, otype.REGULAR)
        self._write_m3u(live)
        self._write_xmltv(live)
        self.written = tuple(e.key for e in live)

    def _number(self, index: int) -> Optional[str]:
        """Channel number for the index-th live event (0-based): major.minor, or None when numbering is off."""
        major = self.args.channel_number
        return None if major is None else f"{major}.{index + 1}"

    def _write_m3u(self, live: List[Event]):
        with open(os.path.join(self.docs, "jellysports.m3u"), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for i, ev in enumerate(live):
                logo = f' tvg-logo="{self.proxy.image_url(ev.image)}"' if ev.image else ""
                if self._number(i):
                    logo += f' tvg-chno="{self._number(i)}"'
                f.write(f'#EXTINF:-1 tvg-id="{ev.key}" tvg-language="English"{logo} group-title="{ev.sport}",{ev.title}\n')
                f.write(f"{self.proxy.stream_url(ev.key)}\n")

    def _write_xmltv(self, live: List[Event]):
        fmt = "%Y%m%d%H%M%S +0000"
        root = ET.Element("tv")
        for i, ev in enumerate(live):
            ch = ET.SubElement(root, "channel", id=ev.key)
            ET.SubElement(ch, "display-name").text = ev.title
            if self._number(i):
                ET.SubElement(ch, "display-name").text = self._number(i)
            if ev.image:
                ET.SubElement(ch, "icon", src=self.proxy.image_url(ev.image))
        for ev in live:
            prog = ET.SubElement(root, "programme", start=ev.kickoff.strftime(fmt),
                                 stop=(ev.kickoff + PROGRAMME_LENGTH).strftime(fmt), channel=ev.key)
            ET.SubElement(prog, "title", lang="en").text = ev.title
            ET.SubElement(prog, "category", lang="en").text = ev.sport
            ET.SubElement(prog, "category", lang="en").text = "sports"
            if ev.image:
                ET.SubElement(prog, "icon", src=self.proxy.image_url(ev.image))
        ET.ElementTree(root).write(os.path.join(self.docs, "jellysports.xml"), encoding="utf-8", xml_declaration=True)


def run(argv: list):
    args = build_parser().parse_args(argv[1:])
    if args.all and args.league:
        p("Cannot pass -a/--all together with --league", colours.FAIL, otype.ERROR)
        sys.exit(2)
    os.environ["verbosity"] = "0" if args.verbose else "1"
    os.environ["no_verbosity"] = "0" if args.quiet else "1"
    header()

    public_url = args.public_url or f"http://localhost:{args.proxy_port}"
    output = os.path.abspath(args.output)
    proxy = StreamProxy(args.proxy_host, args.proxy_port, public_url,
                        docs_dir=os.path.join(output, "docs"), images_dir=os.path.join(output, "images"))
    proxy.start()
    p(f"Stream proxy listening on {args.proxy_host}:{args.proxy_port}; playlists use {public_url}", colours.OKCYAN, otype.REGULAR)
    p(f"Playlist: {proxy.document_url('jellysports.m3u')}   Guide: {proxy.document_url('jellysports.xml')}", colours.OKCYAN, otype.REGULAR)

    listing = ListingClient(args.site)
    collector = Collector(args, proxy, listing)
    try:
        while True:
            now = datetime.datetime.now(UTC)
            if collector.last_listing is None or now - collector.last_listing >= LISTING_REFRESH:
                collector.refresh_listing(now)
            collector.poll(now)
            if collector.needs_write(now) or not os.path.isfile(os.path.join(collector.docs, "jellysports.m3u")):
                collector.write(now)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        listing.close()
        if args.once:
            p(f"Done. Output is in {collector.output}. The proxy stops now; run without --once to serve streams.", colours.OKGREEN, otype.REGULAR)
        proxy.stop()
