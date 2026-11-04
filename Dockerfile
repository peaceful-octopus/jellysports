FROM python:3.12-slim

# Chromium is used only to read the event listing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sportyfin
COPY setup.py setup.cfg README.md LICENSE requirements.txt ./
COPY sportyfin ./sportyfin
RUN pip install --no-cache-dir .

EXPOSE 8099
# Playlists point at the proxy, so players must be able to reach it: map the port and set
# --public-url to an address your Jellyfin server can use, e.g. http://192.168.1.10:8099
CMD ["python3", "-m", "sportyfin", "run", "-a", "-o", "/sportyfin/output", "--proxy-host", "0.0.0.0"]
