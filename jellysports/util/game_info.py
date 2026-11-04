"""Builds the thumbnail shown for each event in Jellyfin."""
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .logos import LogoCache
from .pretty_print import *
from .models import Event

SIZE = 600
DEFAULT_COLOUR = (45, 45, 55)


def dominant_colour(img: Image.Image) -> tuple:
    """Average colour of the logo's visible, non-white pixels, darkened so the logo stays readable."""
    small = img.convert("RGBA").resize((24, 24))
    px = [(r, g, b) for r, g, b, a in small.getdata() if a > 128 and not (r > 235 and g > 235 and b > 235)]
    if not px:
        return DEFAULT_COLOUR
    n = len(px)
    return tuple(int(sum(c[i] for c in px) / n * 0.7) for i in range(3))


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, size: int):
    while size > 10:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(10)


def _logo(path: Optional[str]) -> Optional[Image.Image]:
    if not path:
        return None
    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def generate_img(event: Event, logos: LogoCache, out_dir: str) -> Optional[str]:
    """Returns the path of the event image, creating it once. Events without team names get a text card."""
    path = os.path.join(out_dir, f"{event.key}.jpg")
    if os.path.isfile(path):
        return path
    home = _logo(logos.get(event.home_badge))
    away = _logo(logos.get(event.away_badge))

    left = dominant_colour(home) if home else DEFAULT_COLOUR
    right = dominant_colour(away) if away else DEFAULT_COLOUR
    img = Image.new("RGB", (SIZE, SIZE), left)
    draw = ImageDraw.Draw(img)
    draw.polygon([(int(SIZE * 0.65), 0), (SIZE, 0), (SIZE, SIZE), (int(SIZE * 0.35), SIZE)], fill=right)

    box = int(SIZE * 0.34)
    for logo, cx, cy in ((home, int(SIZE * 0.25), int(SIZE * 0.38)), (away, int(SIZE * 0.75), int(SIZE * 0.62))):
        if logo:
            logo.thumbnail((box, box))
            img.paste(logo, (cx - logo.width // 2, cy - logo.height // 2), logo)

    if not (home or away):
        title_font = _fit_text(draw, event.title, SIZE - 60, 48)
        draw.text((SIZE // 2, SIZE // 2), event.title, fill="white", font=title_font, anchor="mm")
    caption = event.sport
    league_font = _fit_text(draw, caption, SIZE - 60, 30)
    draw.text((SIZE // 2, SIZE - 40), caption, fill=(235, 235, 235), font=league_font, anchor="mm")

    os.makedirs(out_dir, exist_ok=True)
    img.save(path, quality=90)
    return path
