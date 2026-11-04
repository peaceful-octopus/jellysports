# Jellysports

### **For Educational Purposes Only**

## Description

Stream sports events straight from your Jellyfin server. Jellysports reads the live schedule from
[gostreameast.one](https://gostreameast.one), checks which events are on air, and writes an `.m3u` playlist and an
XMLTV guide that Jellyfin's Live TV can use. Team logos are downloaded once and cached, and used to build a thumbnail
for each event.

Jellysports covers every sport the source lists (NBA, NFL, NHL, soccer, college sports, and more). Streams are only
available around game time, so Jellysports checks each event from a few minutes before kickoff, then keeps retrying
for a while after it.

Video is served through a small local proxy built into Jellysports. Jellyfin plays
`http://<host>:8099/stream/<id>.m3u8`; the proxy rebuilds the HLS playlist and converts the source's image-based
segments into regular MPEG-TS on request. Nothing is fetched from the source for a channel nobody is watching.

## Requirements

- Python 3.9 or newer
- Google Chrome or Chromium (used only to read the event listing)
- ffmpeg is not required by Jellysports itself, but Jellyfin needs it to play the streams

## Installation

### Pip

```bash
git clone https://github.com/peaceful-octopus/jellysports.git
cd jellysports
pip install .
```

### Docker

```bash
git clone https://github.com/peaceful-octopus/jellysports.git
cd jellysports
docker build --tag jellysports .
docker run -p 8099:8099 -v <Path Where You Want Output>:/jellysports/output jellysports     python3 -m jellysports run -a -o /jellysports/output --proxy-host 0.0.0.0 --public-url http://<this machine's address>:8099
```

`--public-url` must be an address your Jellyfin server can reach, because it is written into the playlist.

## Usage

Start the service and leave it running (tmux or a similar tool is recommended):

```bash
python3 -m jellysports run -o ~/jellysports-output
```

Useful options:

| Option | Meaning |
|---|---|
| `-l`, `--league TEXT` | Only events whose sport, league or title contains `TEXT` (repeatable), e.g. `-l nba -l hockey` |
| `-a`, `--all` | All sports (the default) |
| `-d`, `--once` | Check every matching event once, ignoring kickoff times, then exit |
| `--lead MIN` / `--window MIN` | Start checking this many minutes before kickoff (5) / keep checking this long after (15) |
| `--interval SEC` | Seconds between checks (30) |
| `--proxy-host`, `--proxy-port` | Where the stream proxy listens (default `127.0.0.1:8099`; use `0.0.0.0` to serve other machines) |
| `--public-url URL` | Address players use to reach the proxy (default `http://localhost:8099`) |
| `--site URL` | Listing site, in case the domain changes |
| `-v` / `-q` | Verbose / errors only |

The playlist and guide are written to `<output>/docs/jellysports.m3u` and `<output>/docs/jellysports.xml`. An event
appears there once a working stream is found and is removed several hours after kickoff.

The proxy also serves both files, plus the event images, so a single base URL is all Jellyfin needs:

- Playlist: `http://<host>:8099/jellysports.m3u`
- Guide: `http://<host>:8099/jellysports.xml`

Chrome is located automatically. Set `CHROME_BIN` and `CHROMEDRIVER` to use a specific browser and driver.

Once you have run the program, make sure to link to the .m3u's in the Jellyfin dashboard:

`Dashboard > Live TV > Tuner Devices (+) > Tuner Type (M3U Tuner) > File or URL (enter the playlist URL above)`

!['Dashboard'](https://i.ibb.co/7Vxvqkp/Screen-Shot-2022-01-11-at-10-47-26-AM.png)

!['Dashboard'](https://i.ibb.co/VH6b0Hc/Screen-Shot-2022-01-11-at-10-47-42-AM.png)

Additionally, make sure to change the "Refresh Guide" setting under:

`Dashboard > Scheduled Tasks > Live TV > Refresh Guide > Task Triggers`


!['Dashboard'](https://i.ibb.co/q7mhTMt/Screen-Shot-2022-01-11-at-10-58-57-AM.png)

!['Dashboard'](https://i.ibb.co/JxcdXC3/Screen-Shot-2022-01-11-at-10-59-11-AM.png)

Once the path has been defined and the settings have been updated, you can check out your streams under:

`Home > Live TV > Channels (at the top)`

!['Dashboard'](https://i.ibb.co/yS5ycS6/Screen-Shot-2022-01-11-at-11-08-08-AM.png)

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Acknowledgements

Jellysports is a fork of [Sportyfin](https://github.com/axelmierczuk/sportyfin) by Axel Mierczuk, released under the
MIT License. The original project is archived. The command-line structure, m3u/XMLTV output and event image generation
come from that project; the event source, stream handling and proxy were rewritten for this fork. See `LICENSE` for the
copyright notices.
