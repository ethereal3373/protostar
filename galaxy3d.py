"""
galaxy3d.py — a 3D galaxy that is built out of your ideas.

Used only by map.py (never by the always-running part).

The galaxy builds itself
------------------------
There is no pre-painted galaxy any more. Every idea brings its own little
patch of the galaxy with it: its star, plus a small cloud of faint stars and
glowing gas around it, smeared along a spiral arm. The core of the galaxy
also grows a bit with every idea. With 2 ideas you see 2 lonely stars;
with hundreds, the clouds overlap and the spiral arms and the bright core
appear by themselves.

New library: numpy
------------------
numpy does maths on whole lists of numbers at once (called "arrays"), in
fast compiled code. Moving 100,000 points in 3D takes it a few
milliseconds; a normal Python loop would take about a second.

3D in a nutshell
----------------
Every point has a position (x, y, z). The galaxy lies flat in x-y; z is
"up". The camera sits somewhere around the galaxy and looks at a target
point. To draw a point we:
  1. measure it from the camera's point of view: how far right (xc),
     how far up (yc) and how far in front (zc) of the camera it is;
  2. divide by the distance: far things get closer to the middle of the
     screen (that's "perspective"):  screen_x = middle + focal * xc / zc
Then we add up the light of all the points into a picture.
"""

import math
import random

import numpy as np
from PIL import Image, ImageFilter

# --- Shape of the spiral ---
ARMS = 2
R_IN = 0.07          # where the arms start (the galaxy's radius is 1)
TAN_PITCH = 0.30     # how tightly the arms wind
ROTATION = 0.4

SPACE = (3, 4, 6)    # colour of empty space: almost black
SPACE_HEX = "#%02x%02x%02x" % SPACE

# Real star colours, from hot blue-white to cool orange.
STAR_COLOURS = [(255, 255, 255), (255, 244, 230), (255, 226, 189), (217, 228, 255), (199, 214, 255)]

PARTICLES_PER_IDEA = 160   # the faint cloud that comes with each idea
DISC_PER_IDEA = 50         # wider, very faint light between the arms
BULGE_PER_IDEA = 30        # the core grows with every idea
DOTS_PER_IDEA = 10         # tiny individual stars near each idea


def arm_angle(r, arm):
    """The angle of spiral arm `arm` at distance r (a "logarithmic spiral")."""
    return ROTATION + arm * 2 * math.pi / ARMS + math.log(max(r, R_IN) / R_IN) / TAN_PITCH


def idea_position(n):
    """
    Where idea number n (0 = oldest) sits in the galaxy, as (x, y, z).
    Ideas take turns between the two arms; older ideas sit closer to the
    core, new ones further out. A position depends only on n, so a star
    never moves when you add new ideas.
    """
    rng = random.Random(n * 7919 + 13)
    # About 1000 ideas fill the galaxy out to its edge (radius 1); after that
    # it keeps growing, more and more slowly.
    if n < 1000:
        r = 0.12 + 0.85 * math.sqrt(n / 1000)
    else:
        r = 0.97 + 0.2 * math.log(n / 1000)
    r += rng.gauss(0, 0.02)
    # Stars spread across the arm's width, not on a thin line.
    angle = arm_angle(r, n % ARMS) + rng.gauss(0, 0.17)
    return (r * math.cos(angle), r * math.sin(angle), rng.gauss(0, 0.015))


# ---------------------------------------------------------------------------
# The scene: all the points of light
# ---------------------------------------------------------------------------

class Scene:
    """All the points that make up the galaxy, built from a number of ideas."""

    def __init__(self, idea_count, colour_index, note_counts=()):
        """
        `colour_index(n)` tells which STAR_COLOURS entry idea n uses.
        `note_counts[n]` is how many notes idea n has: each note becomes a
        tiny, faint star right next to its idea (like planets around a sun).
        """
        self.count = idea_count
        self.ideas = np.array([idea_position(n) for n in range(idea_count)], dtype=np.float32).reshape(-1, 3)
        self.idea_colours = [STAR_COLOURS[colour_index(n)] for n in range(idea_count)]

        points, light = [], []
        dots, dot_light = [], []
        for n in range(idea_count):
            p, l, d, dl = self._cloud_for_idea(n)
            points.append(p); light.append(l); dots.append(d); dot_light.append(dl)
        if idea_count:
            p, l = self._bulge(idea_count)
            points.append(p); light.append(l)
            self.points = np.concatenate(points).astype(np.float32)
            self.light = np.concatenate(light).astype(np.float32)
            self.dots = np.concatenate(dots).astype(np.float32)
            self.dot_light = np.concatenate(dot_light).astype(np.float32)
        else:
            self.points = np.zeros((0, 3), np.float32)
            self.light = np.zeros((0, 3), np.float32)
            self.dots = np.zeros((0, 3), np.float32)
            self.dot_light = np.zeros((0, 3), np.float32)

        # Notes: tiny stars circling close to their idea.
        note_points, note_light = [], []
        for n, k in enumerate(note_counts):
            cx, cy, cz = self.ideas[n]
            colour = np.array(self.idea_colours[n]) / 255
            for j in range(k):
                angle = n + j * 2.39996              # the golden angle again: evenly spread
                dist = 0.006 + 0.0025 * j
                note_points.append((cx + dist * math.cos(angle), cy + dist * math.sin(angle),
                                    cz + 0.002 * math.sin(3 * angle)))
                note_light.append(colour * 110)
        self.notes = np.array(note_points, np.float32).reshape(-1, 3)
        self.note_light = np.array(note_light, np.float32).reshape(-1, 3)

        # Very faint stars far away in every direction (the night sky).
        rng = np.random.default_rng(7)
        sky = rng.normal(size=(5000, 3))
        self.sky = (sky / np.linalg.norm(sky, axis=1, keepdims=True)).astype(np.float32)
        self.sky_light = (6 + 34 * rng.random(5000) ** 5).astype(np.float32)

    @staticmethod
    def _cloud_for_idea(n):
        """The cloud of faint stars and gas that idea n adds to its spiral arm."""
        rng = np.random.default_rng(n + 1000)
        x, y, z = idea_position(n)
        r0 = math.hypot(x, y)
        arm = n % ARMS

        # Gas and faint stars, smeared ALONG the arm: we move each particle a
        # bit in or out (dr) and then follow the spiral's angle at that radius.
        k = PARTICLES_PER_IDEA
        r = r0 + rng.normal(0, 0.04 + 0.02 * r0, k)
        r = np.clip(r, 0.03, None)
        # Follow the arm through the idea's own position (so the cloud sits around its star).
        own_angle = math.atan2(y, x)
        base = ROTATION + arm * math.pi + math.log(max(r0, R_IN) / R_IN) / TAN_PITCH
        angle = own_angle + (np.log(np.maximum(r, R_IN) / R_IN) / TAN_PITCH
                             - (base - ROTATION - arm * math.pi))
        angle += rng.normal(0, 0.12 + 0.05 * r0, k)          # spread across the arm
        cloud = np.stack([r * np.cos(angle), r * np.sin(angle), rng.normal(z, 0.014, k)], axis=1)
        # Mostly young blue-white stars and gas, sometimes a warmer patch.
        warm = rng.random(k) < 0.2
        colour = np.where(warm[:, None], [1.0, 0.86, 0.70], [0.66, 0.74, 0.92])
        cloud_light = colour * rng.uniform(0.3, 1.0, (k, 1))

        # A wider, much fainter haze: the disc between the arms.
        k2 = DISC_PER_IDEA
        rr = np.abs(r0 + rng.normal(0, 0.10, k2))
        aa = math.atan2(y, x) + rng.normal(0, 0.8, k2)
        disc = np.stack([rr * np.cos(aa), rr * np.sin(aa), rng.normal(0, 0.03, k2)], axis=1)
        disc_light = np.tile([0.55, 0.55, 0.58], (k2, 1)) * 0.45

        # A few individual tiny stars, for sparkle.
        k3 = DOTS_PER_IDEA
        dr = r0 + rng.normal(0, 0.04, k3)
        da = own_angle + (np.log(np.maximum(dr, R_IN) / R_IN) - math.log(max(r0, R_IN) / R_IN)) / TAN_PITCH
        da += rng.normal(0, 0.10, k3)
        dots = np.stack([dr * np.cos(da), dr * np.sin(da), rng.normal(z, 0.012, k3)], axis=1)
        dot_light = np.array([STAR_COLOURS[i] for i in rng.integers(0, 5, k3)]) / 255 * rng.uniform(25, 70, (k3, 1))

        return (np.concatenate([cloud, disc]), np.concatenate([cloud_light, disc_light]), dots, dot_light)

    @staticmethod
    def _bulge(idea_count):
        """The warm, round core. More ideas = a bigger, brighter core."""
        rng = np.random.default_rng(1)
        k = min(BULGE_PER_IDEA * idea_count, 30_000)
        size = 0.05 + 0.03 * min(1.0, idea_count / 200)
        pts = rng.normal(0, 1, (k, 3)) * [size, size, size * 0.7]
        light = np.tile([1.0, 0.85, 0.64], (k, 1)) * rng.uniform(0.4, 1.0, (k, 1))
        return pts, light


# ---------------------------------------------------------------------------
# The camera
# ---------------------------------------------------------------------------

# How "zoomed" the lens is. Smaller = wider view (like a phone's 0.5x lens).
# 0.45 gives about 100 degrees across the short side of the window.
FOCAL = 0.45


def focal_length(width, height):
    return FOCAL * min(width, height)


class Camera:
    """
    A free-flying camera (like in Roblox Studio).
    position = where the camera is, as (x, y, z)
    yaw      = which way it faces, turning left/right
    pitch    = which way it faces, up/down (negative = looking down)
    """

    def __init__(self, position=(0.0, -1.0, 1.0), yaw=0.0, pitch=-0.7):
        self.position = np.array(position, np.float64)
        self.yaw = yaw
        self.pitch = pitch

    def copy(self):
        return Camera(self.position.copy(), self.yaw, self.pitch)

    def forward(self):
        cp = math.cos(self.pitch)
        return np.array([cp * math.sin(self.yaw), cp * math.cos(self.yaw), math.sin(self.pitch)])

    def basis(self):
        """The camera's position and its right / up / forward directions."""
        forward = self.forward()
        right = np.cross(forward, [0.0, 0.0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return self.position, right, up, forward

    def look_at(self, point, distance):
        """Place the camera `distance` away from `point`, facing it (keeps the current angle)."""
        self.position = np.asarray(point, np.float64) - self.forward() * distance

    def ray(self, sx, sy, width, height):
        """The direction from the camera through screen pixel (sx, sy)."""
        _, right, up, forward = self.basis()
        f = focal_length(width, height)
        d = forward + right * (sx - width / 2) / f - up * (sy - height / 2) / f
        return d / np.linalg.norm(d)

    def project(self, points, width, height):
        """Screen x, y and the distance in front of the camera, for many points at once."""
        position, right, up, forward = self.basis()
        v = points - position
        xc, yc, zc = v @ right, v @ up, v @ forward
        focal = focal_length(width, height)
        safe = np.maximum(zc, 1e-4)
        sx = width / 2 + focal * xc / safe
        sy = height / 2 - focal * yc / safe
        return sx, sy, zc, focal


# ---------------------------------------------------------------------------
# Drawing a frame
# ---------------------------------------------------------------------------

GLOW_SCALE = 0.5       # the soft glow is drawn at half resolution (4x fewer pixels)
EXPOSURE = 1.2e-5      # how bright the glow looks overall


def render(scene, camera, width, height):
    """
    Draw the galaxy as seen by `camera`. Returns the picture and, for every
    idea, where its star landed on screen (x, y) and whether it's visible.
    """
    # --- 1. The soft glow (gas + faint stars) ---
    # From far away it's drawn at half resolution and blurred (soft and cheap).
    # Up close the particles are far apart, and blurring them makes grey fog:
    # then we draw at full resolution with almost no blur, so it looks like
    # fine star dust instead.
    position, _, _, forward = camera.basis()
    close = False
    if len(scene.points):
        sample = scene.points[::25]
        close = float(np.median((sample - position) @ forward)) < 0.45
    glow_scale = 1.0 if close else GLOW_SCALE
    gw, gh = max(1, int(width * glow_scale)), max(1, int(height * glow_scale))
    glow = np.zeros((gh * gw, 3), np.float32)
    if len(scene.points):
        sx, sy, zc, focal = camera.project(scene.points, gw, gh)
        ok = (zc > 0.01) & (sx >= 0) & (sx < gw) & (sy >= 0) & (sy < gh)
        index = sy[ok].astype(np.int64) * gw + sx[ok].astype(np.int64)
        # Each particle's light is scaled by (focal / distance)^2: when you zoom
        # in, the same particles spread over more pixels, so each pixel must get
        # more light per particle to keep the galaxy equally bright.
        # More ideas = more overlapping light, so we lower the exposure as the
        # galaxy grows (like a camera does in bright light).
        exposure = EXPOSURE * (30 / max(30, scene.count)) ** 0.55
        scale = (focal / zc[ok]) ** 2 * exposure
        for ch in range(3):
            # bincount adds up all the light that lands on each pixel.
            glow[:, ch] = np.bincount(index, weights=scene.light[ok, ch] * scale, minlength=gw * gh)
        # Soften: closer views spread particles out, so blur more.
        # Up close, particles are far apart: a big blur would turn them into
        # grey blobs, so the blur stays small and they show as fine grain.
        typical = float(np.median(zc[ok])) if ok.any() else 1.0
        blur = 0.8 if close else min(2.0, max(0.8, 0.010 * focal / typical))
    else:
        blur = 1.0
    # "Tone mapping": 1 - e^(-light) grows quickly at first, then levels off
    # at 1, so bright areas glow without turning into flat white blobs.
    glow = (1.0 - np.exp(-glow)) * 255
    glow_img = Image.fromarray(glow.reshape(gh, gw, 3).astype(np.uint8), "RGB")
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(blur))
    frame = np.asarray(glow_img.resize((width, height), Image.BILINEAR), dtype=np.float32).copy()
    frame += SPACE

    # --- 2. The night sky: very faint, far-away stars ---
    position, right, up, forward = camera.basis()
    d = scene.sky
    xc, yc, zc = d @ right, d @ up, d @ forward
    focal = focal_length(width, height)
    vis = zc > 0.05
    sx = (width / 2 + focal * xc[vis] / zc[vis]).astype(np.int64)
    sy = (height / 2 - focal * yc[vis] / zc[vis]).astype(np.int64)
    inside = (sx >= 0) & (sx < width) & (sy >= 0) & (sy < height)
    np.add.at(frame, (sy[inside], sx[inside]), scene.sky_light[vis][inside, None])

    # --- 3. Tiny individual stars in the galaxy ---
    if len(scene.dots):
        sx, sy, zc, _ = camera.project(scene.dots, width, height)
        ok = (zc > 0.01) & (sx >= 0) & (sx < width) & (sy >= 0) & (sy < height)
        np.add.at(frame, (sy[ok].astype(np.int64), sx[ok].astype(np.int64)), scene.dot_light[ok])

    # --- 3b. Notes: tiny stars right next to their idea ---
    if len(scene.notes):
        sx, sy, zc, focal = camera.project(scene.notes, width, height)
        for i in np.nonzero(zc > 0.005)[0]:
            size = focal * 0.0016 / zc[i]
            if size < 0.35:
                continue                           # too far away to see
            radius = min(2.0, max(0.7, size))
            colour = tuple(int(c) for c in scene.note_light[i] / 110 * 255)
            _add_sprite(frame, star_sprite(colour, round(radius * 4) / 4, 0.5), sx[i], sy[i])

    # --- 4. The idea stars ---
    screen = np.zeros((scene.count, 2), np.float32)
    visible = np.zeros(scene.count, bool)
    if scene.count:
        sx, sy, zc, focal = camera.project(scene.ideas, width, height)
        screen[:, 0], screen[:, 1] = sx, sy
        for n in np.argsort(-zc):                       # far ones first
            if zc[n] <= 0.01:
                continue
            size = focal * 0.004 / zc[n]           # how big the star would look
            radius = min(4.5, max(0.9, size))
            # Stars too far away to be big get dimmer instead (like real stars),
            # so a zoomed-out galaxy doesn't melt into one white blob.
            brightness = 0.85 * min(1.0, max(0.3, size / 2.0))
            sprite = star_sprite(scene.idea_colours[n], round(radius * 4) / 4, round(brightness, 1))
            if _add_sprite(frame, sprite, sx[n], sy[n]):
                visible[n] = True

    picture = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8), "RGB")
    return picture, screen, visible


def _add_sprite(frame, sprite, x, y):
    """Add a star picture onto the frame (adding light, like real light does)."""
    h, w = sprite.shape[:2]
    x0, y0 = int(round(x)) - w // 2, int(round(y)) - h // 2
    fh, fw = frame.shape[:2]
    if x0 >= fw or y0 >= fh or x0 + w <= 0 or y0 + h <= 0:
        return False
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = min(w, fw - x0), min(h, fh - y0)
    frame[y0 + sy0:y0 + sy1, x0 + sx0:x0 + sx1] += sprite[sy0:sy1, sx0:sx1]
    return True


_sprites = {}


def star_sprite(colour, radius, brightness=1.0):
    """
    One idea star, as an array of light values. Made once per colour and
    size, then reused. It's drawn at 3x the size and shrunk down (called
    "supersampling"), which gives smooth edges instead of hard pixels.

    A realistic star: a small, sharp, white-hot centre and a thin coloured
    glow right around it. No big fog: real stars are points of light.
    Close-up stars get very faint, thin rays (like in telescope photos).
    """
    key = (colour, radius, brightness)
    if key in _sprites:
        return _sprites[key]
    ss = 3                                     # supersampling factor
    size = int(radius * 8) | 1
    n = size * ss
    coords = (np.arange(n) + 0.5) / ss - size / 2
    x, y = np.meshgrid(coords, coords)
    d = np.hypot(x, y) / radius
    core = np.exp(-(d / 0.42) ** 2)                      # sharp, bright centre
    glow = 0.16 * np.exp(-(d / 0.95) ** 2)               # thin halo right around it
    haze = 0.015 * np.exp(-d / 1.6)                      # just a hint of glow
    # Rays: thin, faint, only for close (big) stars.
    ray_strength = 0.06 * min(1.0, max(0.0, (radius - 2.5) / 2))
    rays = ray_strength * (np.exp(-(y / 0.35) ** 2) + np.exp(-(x / 0.35) ** 2)) * np.exp(-d / 1.6)
    c = np.array(colour, np.float32) / 255
    white = np.ones(3, np.float32)
    light = (core[..., None] * white + (glow + haze + rays)[..., None] * c) * 255
    # Shrink 3x3 blocks into single pixels (the supersampling step).
    light = light.reshape(size, ss, size, ss, 3).mean(axis=(1, 3)).astype(np.float32) * brightness
    _sprites[key] = light
    return light
