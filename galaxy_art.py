"""
galaxy_art.py — paints the galaxy picture behind the map, and the idea stars.

Used only by map.py (never by the always-running part).

New library: Pillow (imported as PIL)
-------------------------------------
Pillow is the most common Python library for making and editing images.
Tkinter alone can only draw flat shapes; Pillow lets us blur, blend and
colour pixels, which is what a soft, glowing galaxy needs.
Install it once with:   python -m pip install pillow

How the galaxy is painted
-------------------------
1. We throw a few hundred thousand invisible "particles" onto a small grid,
   following the shape of a spiral galaxy (a bright core, two spiral arms,
   dark dust lanes along the arms, a faint disc). Each grid cell counts how
   many particles landed on it: that's how bright that spot of sky is.
2. The counts become a small greyscale picture, which we tint with natural
   colours (warm yellow core, cool white-blue arms) and blend together.
3. We enlarge and blur it so it looks like soft light, then sprinkle dim
   background stars on top.
4. The finished picture is saved in cache/ so it's only painted once:
   after that, the map opens instantly.

Painting is "deterministic": a fixed random seed means the galaxy comes out
exactly the same every time.
"""

import math
import random
from array import array
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# --- Size of the full galaxy picture (in pixels) ---
SRC_W, SRC_H = 3072, 2048
CENTER_X, CENTER_Y = SRC_W / 2, SRC_H / 2
GALAXY_R = 0.46 * SRC_H          # radius of the galaxy disc, in pixels

# --- Shape of the spiral (shared by the picture AND the idea stars) ---
ARMS = 2                         # number of spiral arms
R_IN = 0.07                      # where the arms start (fraction of the radius)
TAN_PITCH = 0.30                 # how tightly the arms wind (smaller = tighter)
ROTATION = 0.4                   # turns the whole galaxy a little (radians)

SPACE = (4, 5, 8)                # the colour of empty space: almost black
SPACE_HEX = "#%02x%02x%02x" % SPACE

CACHE_FILE = Path(__file__).parent / "cache" / "galaxy_v1.png"


# ---------------------------------------------------------------------------
# Geometry: where things are
# ---------------------------------------------------------------------------

def arm_angle(r, arm):
    """
    The angle of spiral arm number `arm` at distance r from the centre.
    This is a "logarithmic spiral", the shape real spiral galaxies have:
    the further out you go, the more the arm has turned.
    """
    return ROTATION + arm * 2 * math.pi / ARMS + math.log(max(r, R_IN) / R_IN) / TAN_PITCH


def to_pixels(r, angle):
    """Convert (distance, angle) into (x, y) pixels on the galaxy picture."""
    return (CENTER_X + GALAXY_R * r * math.cos(angle),
            CENTER_Y + GALAXY_R * r * math.sin(angle))


def idea_position(n):
    """
    Where idea number n (0 = oldest) sits in the galaxy, in picture pixels.

    Ideas line up along the spiral arms, alternating between the two arms.
    Older ideas are near the core and new ones further out, so the galaxy
    grows outwards as you add ideas. A position only depends on n, so a
    star never moves when new ideas are added.
    """
    rng = random.Random(n * 7919 + 13)   # small, repeatable "random" wobble
    r = min(0.97, 0.16 + 0.052 * math.sqrt(n))
    arm = n % ARMS
    angle = arm_angle(r, arm) + rng.gauss(0, 0.07)
    r += rng.gauss(0, 0.015)
    return to_pixels(r, angle)


# ---------------------------------------------------------------------------
# Painting the galaxy
# ---------------------------------------------------------------------------

GRID_W, GRID_H = 1536, 1024      # the grid we count particles on (half the picture size)
GRID_SCALE = GRID_W / SRC_W      # grid cells per picture pixel


def _density(particles, rng, gamma=0.5, clip=1.0):
    """
    Drop particles on the grid and return a greyscale image of the counts.
    `particles` is a function that returns (x, y, weight) in picture pixels.
    `clip` < 1 lets the brightest spots "saturate", so fainter detail shows more.
    """
    # array = a compact list of numbers (much less memory than a normal list).
    counts = array("f", bytes(4 * GRID_W * GRID_H))
    for x, y, w in particles(rng):
        gx, gy = int(x * GRID_SCALE), int(y * GRID_SCALE)
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
            counts[gy * GRID_W + gx] += w
    peak = (max(counts) or 1.0) * clip
    # A power below 1 (like a square root) lifts faint areas, as our eyes do.
    data = bytes(min(255, int(255 * (c / peak) ** gamma)) for c in counts)
    return Image.frombytes("L", (GRID_W, GRID_H), data)


def _arm_particles(rng, count=240_000, offset=0.0, spread=1.0, reach=1.15, even=False):
    """
    Particles along the spiral arms.
    `offset` turns them a little (used to put dust lanes beside the arms),
    `spread` makes the arms wider or thinner, `reach` is how far out they go.
    `even=True` gives the same strength all along the arm (for dust), instead
    of fading outwards.
    """
    for i in range(count):
        arm = i % ARMS
        r = R_IN + (reach - R_IN) * rng.random() ** 0.9
        angle = arm_angle(r, arm) + offset + rng.gauss(0, (0.10 + 0.10 * r) * spread)
        r += rng.gauss(0, (0.015 + 0.05 * r) * spread)   # arms get wider further out
        x, y = to_pixels(r, angle)
        # Brightness fades towards the edge, and waves gently along the arm
        # so the arms aren't evenly lit from end to end.
        wave = 0.75 + 0.25 * math.sin(3.1 * angle + arm)
        if even:
            # Outer parts of the arm are longer, so their particles are spread
            # thinner: giving them more weight (r) evens out the strength.
            yield x, y, r * wave
        else:
            yield x, y, math.exp(-2.0 * r) * wave


def _clump_particles(rng, clumps=2600, per_clump=90):
    """
    Clumpy arms: real arms are made of many star clouds, not a smooth ribbon.
    We pick clump centres along the arms (and a few on faint side-branches
    called "spurs"), then scatter particles tightly around each centre.
    """
    for i in range(clumps):
        arm = i % ARMS
        r = R_IN + (1.0 - R_IN) * rng.random() ** 0.8
        angle = arm_angle(r, arm) + rng.gauss(0, 0.13)
        if rng.random() < 0.25:                 # a spur: branches off at a steeper angle
            angle += rng.uniform(0.15, 0.5)
            r += rng.uniform(0.02, 0.08)
        cx, cy = to_pixels(r, angle)
        size = GALAXY_R * rng.uniform(0.004, 0.016) * (0.6 + r)
        weight = math.exp(-1.4 * r) * rng.uniform(0.3, 1.0)
        for _ in range(per_clump):
            yield cx + rng.gauss(0, size), cy + rng.gauss(0, size), weight


def _disc_particles(rng, count=120_000):
    """A faint, smooth disc of light between the arms."""
    for _ in range(count):
        r = rng.expovariate(1 / 0.36)
        x, y = to_pixels(r, rng.uniform(0, 2 * math.pi))
        # Weight r: circles near the centre are small, so particles pile up
        # there; this evens it out into a smooth disc that fades gently.
        yield x, y, r


def _core_particles(rng, count=70_000):
    """The bright, round centre of the galaxy."""
    for _ in range(count):
        x = CENTER_X + rng.gauss(0, 0.075 * GALAXY_R)
        y = CENTER_Y + rng.gauss(0, 0.065 * GALAXY_R)
        yield x, y, 1.0


def _tint(grey, colour, strength):
    """Turn a greyscale image into a coloured one: white -> `colour` * strength."""
    channels = [grey.point(lambda v, c=c: int(v * c * strength / 255)) for c in colour]
    return Image.merge("RGB", channels)


def render_galaxy():
    """Paint the whole galaxy picture (takes a couple of seconds)."""
    rng = random.Random(2026)
    blur = ImageFilter.GaussianBlur

    # Each layer is a separate greyscale "light map", blurred to look soft.
    arms = _density(_arm_particles, rng).filter(blur(5))
    clumps = _density(_clump_particles, rng, gamma=0.6, clip=0.5).filter(blur(1.3))
    # Dust lanes: thin, dark bands running just along the inside edge of each arm.
    dust = _density(lambda g: _arm_particles(g, 220_000, offset=-0.07, spread=0.3, reach=0.95,
                                             even=True),
                    rng, gamma=0.9, clip=0.5).filter(blur(1.8))
    disc = _density(_disc_particles, rng, gamma=0.6, clip=0.6).filter(blur(14))
    core = _density(_core_particles, rng, gamma=0.6).filter(blur(10))
    halo = _density(lambda g: _core_particles(g, 50_000), rng, gamma=0.35).filter(blur(40))

    knots = Image.new("L", (GRID_W, GRID_H), 0)   # a few young, hot star clusters
    draw = ImageDraw.Draw(knots)
    for i in range(90):
        r = 0.2 + 0.7 * rng.random()
        x, y = to_pixels(r + rng.gauss(0, 0.01), arm_angle(r, i % ARMS) + rng.gauss(0, 0.06))
        gx, gy, s = x * GRID_SCALE, y * GRID_SCALE, rng.uniform(0.5, 2.0)
        draw.ellipse((gx - s, gy - s, gx + s, gy + s), fill=int(rng.uniform(60, 170)))
    knots = knots.filter(blur(1.5))

    # Natural colours, kept dark: this is space, not a light show.
    picture = Image.new("RGB", (GRID_W, GRID_H), SPACE)
    picture = ImageChops.add(picture, _tint(halo, (190, 170, 140), 0.10))
    picture = ImageChops.add(picture, _tint(disc, (150, 140, 128), 0.22))
    picture = ImageChops.add(picture, _tint(arms, (150, 165, 190), 0.30))
    picture = ImageChops.add(picture, _tint(clumps, (175, 188, 215), 0.38))
    picture = ImageChops.add(picture, _tint(knots, (170, 192, 255), 0.30))
    picture = ImageChops.add(picture, _tint(core, (255, 220, 165), 0.80))
    # Dust lanes block light: multiply by "1 - dust" to darken those areas.
    shade = dust.point(lambda v: 255 - int(v * 0.7))
    picture = ImageChops.multiply(picture, Image.merge("RGB", [shade] * 3))

    # Enlarge to full size; BICUBIC smoothing + a light blur hides the grid.
    picture = picture.resize((SRC_W, SRC_H), Image.BICUBIC).filter(blur(1.2))

    _sprinkle_background_stars(picture, rng)
    return picture


def _sprinkle_background_stars(picture, rng):
    """
    Tiny, DIM stars. They're only scenery, so they stay faint and never
    compete with your ideas for attention.
    """
    draw = ImageDraw.Draw(picture)
    tints = [(1.0, 1.0, 1.0), (1.0, 0.95, 0.85), (0.85, 0.9, 1.0), (1.0, 0.88, 0.75)]

    def star(x, y, brightness):
        t = rng.choice(tints)
        old = picture.getpixel((int(x), int(y)))
        new = tuple(min(255, o + int(brightness * k)) for o, k in zip(old, t))
        draw.point((x, y), fill=new)

    # Everywhere: a thin scattering of very faint stars.
    for _ in range(9000):
        star(rng.uniform(0, SRC_W - 1), rng.uniform(0, SRC_H - 1), 12 + 50 * rng.random() ** 4)
    # Inside the galaxy: more stars, following the arms.
    for x, y, _ in _arm_particles(rng, 14_000):
        if 0 <= x < SRC_W and 0 <= y < SRC_H:
            star(x, y, 14 + 45 * rng.random() ** 3)


def load_galaxy():
    """Return the galaxy picture: from the cache if it exists, otherwise paint it."""
    if CACHE_FILE.exists():
        return Image.open(CACHE_FILE).convert("RGB")
    picture = render_galaxy()
    CACHE_FILE.parent.mkdir(exist_ok=True)
    picture.save(CACHE_FILE)
    return picture


# ---------------------------------------------------------------------------
# The idea stars
# ---------------------------------------------------------------------------

# Real star colours (from hot blue-white to cool orange), kept gentle.
STAR_COLOURS = [(255, 255, 255), (255, 244, 230), (255, 226, 189), (217, 228, 255), (199, 214, 255)]


def star_sprite(colour, radius, glow=1.0):
    """
    Draw one idea star as a small transparent picture (RGBA = colours + see-through).
    A bright centre, a soft halo, and faint cross-shaped "spikes" like in
    telescope photos. `glow` > 1 makes it bigger and brighter (for hovering).
    """
    radius *= glow
    size = int(radius * 9) | 1               # odd number, so there's a centre pixel
    mid = size // 2
    pixels = []
    for y in range(size):
        for x in range(size):
            dx, dy = x - mid, y - mid
            d = math.hypot(dx, dy) / radius
            core = max(0.0, 1.0 - d * d * 1.6)                    # solid bright centre
            halo = 0.55 * glow * math.exp(-(d / 1.9) ** 2)        # soft light around it
            # Spikes: bright along the horizontal and vertical lines through the middle.
            spike = 0.0
            if abs(dx) < 0.8 or abs(dy) < 0.8:
                spike = 0.35 * glow * math.exp(-d / 2.2)
            a = min(1.0, core + halo * 0.6 + spike)
            # The very centre is white; the colour shows in the halo.
            white = min(1.0, core * 1.2)
            r, g, b = (int(c + (255 - c) * white) for c in colour)
            pixels.append((r, g, b, int(255 * a)))
    sprite = Image.new("RGBA", (size, size))
    sprite.putdata(pixels)
    return sprite
