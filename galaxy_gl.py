"""
galaxy_gl.py — draws the galaxy with the GRAPHICS CARD (GPU).

Why
---
Before, every frame was calculated by the processor (CPU), pixel by pixel,
in Python: about 20 pictures per second at best, and the PC got busy.
A graphics card is built for exactly this: it works on thousands of points
at the same time. The same galaxy now takes about 1-3 milliseconds per
frame, so moving around is as smooth as your screen allows.

New concepts
------------
- OpenGL: the standard "language" programs use to talk to graphics cards.
- moderngl: a Python library that makes OpenGL easy to use.
- pyopengltk: gives us a Tkinter frame the graphics card can draw into, so
  the sidebar and search panel stay normal Tkinter.
- Shaders: tiny programs that run ON the graphics card, written in GLSL (a
  language similar to C). A "vertex shader" runs once per point and decides
  where it lands on screen; a "fragment shader" runs once per pixel and
  decides its colour. Thousands of copies run at the same time.
- Buffer: a block of numbers (positions, colours) copied to the graphics
  card's own memory once, so it doesn't need to be sent again every frame.

The picture is drawn in two steps:
  1. All the light (gas, dust, stars) is ADDED UP into an invisible
     picture that can hold values above "fully bright" (a float texture).
  2. That picture is "tone mapped" onto the screen: 1 - e^(-light), so
     bright areas glow without turning into flat white blobs.
"""

import numpy as np
import moderngl
from OpenGL import GL
from pyopengltk import OpenGLFrame

import galaxy3d as g3d

# The part of every vertex shader that turns a 3D point into a screen position.
# It's the same maths as galaxy3d.Camera.project (so clicking stars matches).
PROJECT = """
uniform vec3 cam_pos;
uniform vec3 cam_right;
uniform vec3 cam_up;
uniform vec3 cam_fwd;
uniform vec2 screen;      // width, height in pixels
uniform float focal;      // the lens: pixels per unit at distance 1

vec4 project(vec3 p, out float depth) {
    vec3 v = p - cam_pos;
    depth = dot(v, cam_fwd);
    if (depth < 0.003) return vec4(0.0, 0.0, 2.0, 1.0);      // behind us: off screen
    float x = dot(v, cam_right) * focal / (screen.x * 0.5);
    float y = dot(v, cam_up) * focal / (screen.y * 0.5);
    return vec4(x, y, 0.0, depth);   // the card divides by `depth` for us: perspective
}
"""

# --- 1. Soft gas glow: big blurry points that fade out when very close ---
GAS_VS = "#version 330\n" + PROJECT + """
in vec3 pos;
in vec3 light;
uniform float exposure;
out vec3 v_light;
void main() {
    float depth;
    gl_Position = project(pos, depth);
    float true_size = 0.016 * focal / max(depth, 0.003);    // how big this puff of gas really looks
    float size = clamp(true_size, 2.0, 60.0);
    // Keep the same total light whatever the size, and fade the puffs out
    // when they get huge (very close): close up you see fine dust, not fog.
    float fade = clamp((60.0 - true_size) / 30.0, 0.0, 1.0);
    v_light = light * exposure * (true_size * true_size) / (size * size) * fade;
    gl_PointSize = size;
}
"""
GAS_FS = """#version 330
in vec3 v_light;
out vec4 colour;
void main() {
    vec2 d = gl_PointCoord * 2.0 - 1.0;
    colour = vec4(v_light * exp(-dot(d, d) * 4.0), 1.0);
}
"""

# --- 2. Crisp dust: every gas particle also as a tiny sharp star, visible up close ---
DUST_VS = "#version 330\n" + PROJECT + """
in vec3 pos;
in vec3 light;
uniform float strength;
uniform float near_range;   // > 0: only noticeable closer than this; 0: always visible
out vec3 v_light;
void main() {
    float depth;
    gl_Position = project(pos, depth);
    float near = near_range > 0.0 ? clamp(near_range / max(depth, 0.003), 0.0, 1.0) : 1.0;
    v_light = light * strength * near * near;
    gl_PointSize = 2.0;
}
"""
DUST_FS = """#version 330
in vec3 v_light;
out vec4 colour;
void main() {
    vec2 d = gl_PointCoord * 2.0 - 1.0;
    colour = vec4(v_light * max(0.0, 1.0 - dot(d, d)), 1.0);
}
"""

# --- 3. The night sky: directions, infinitely far away (they never get closer) ---
SKY_VS = "#version 330\n" + PROJECT + """
in vec3 dir;
in float bright;
out float v_bright;
void main() {
    float depth;
    gl_Position = project(cam_pos + dir * 1000.0, depth);
    v_bright = bright;
    gl_PointSize = 1.6;
}
"""
SKY_FS = """#version 330
in float v_bright;
out vec4 colour;
void main() {
    vec2 d = gl_PointCoord * 2.0 - 1.0;
    colour = vec4(vec3(v_bright) * max(0.0, 1.0 - dot(d, d)), 1.0);
}
"""

# --- 4. Idea stars (and notes): sharp centre, thin halo, faint rays up close ---
STAR_VS = "#version 330\n" + PROJECT + """
in vec3 pos;
in vec3 tint;
in float bright;     // activity glow * highlight
in float scale;      // bigger for "growing" ideas, etc.
uniform float base;  // star size factor (ideas vs notes)
uniform float min_radius;
out vec3 v_tint;
out float v_bright;
out float v_radius;
void main() {
    float depth;
    gl_Position = project(pos, depth);
    float radius = clamp(base * focal / max(depth, 0.003), min_radius, 4.5) * scale;
    // Far stars can't get smaller than min_radius, so they get dimmer instead.
    float dim = clamp(base * focal / max(depth, 0.003) / 2.0, 0.55, 1.0);
    v_tint = tint;
    v_bright = bright * dim;
    v_radius = radius;
    gl_PointSize = radius * 8.0;
}
"""
STAR_FS = """#version 330
in vec3 v_tint;
in float v_bright;
in float v_radius;
out vec4 colour;
void main() {
    vec2 p = (gl_PointCoord * 2.0 - 1.0) * 4.0;     // in units of the star's radius
    float d = length(p);
    float core = exp(-pow(d / 0.42, 2.0));
    float halo = 0.16 * exp(-pow(d / 0.95, 2.0)) + 0.015 * exp(-d / 1.6);
    // Rays: thin lines (0.35 pixels wide) through the centre, only for close, big stars.
    float ray_strength = 0.06 * clamp((v_radius - 2.5) / 2.0, 0.0, 1.0);
    float rays = ray_strength * (exp(-pow(p.y * v_radius / 0.35, 2.0))
                               + exp(-pow(p.x * v_radius / 0.35, 2.0))) * exp(-d / 1.6);
    vec3 light = vec3(core) + (halo + rays) * v_tint;
    colour = vec4(light * v_bright * 2.0, 1.0);
}
"""

# --- 5. Tone mapping: the added-up light -> the screen ---
TONE_VS = """#version 330
in vec2 corner;
out vec2 uv;
void main() { uv = corner * 0.5 + 0.5; gl_Position = vec4(corner, 0.0, 1.0); }
"""
TONE_FS = """#version 330
uniform sampler2D light;
uniform vec3 space;
in vec2 uv;
out vec4 colour;
void main() {
    vec3 c = texture(light, uv).rgb;
    colour = vec4(space + (1.0 - exp(-c)), 1.0);
}
"""

# --- 6. Lines (constellations) and the selection ring, drawn on top ---
LINE_VS = "#version 330\n" + PROJECT + """
in vec3 pos;
in vec3 tint;       // each constellation has its own soft colour
in float alpha;
out vec4 v_colour;
void main() {
    float depth;
    gl_Position = project(pos, depth);
    v_colour = vec4(tint, alpha);
}
"""
LINE_FS = """#version 330
in vec4 v_colour;
out vec4 colour;
void main() { colour = v_colour; }
"""
RING_VS = "#version 330\n" + PROJECT + """
in vec3 pos;
void main() { float depth; gl_Position = project(pos, depth); gl_PointSize = 26.0; }
"""
RING_FS = """#version 330
out vec4 colour;
void main() {
    float r = length(gl_PointCoord * 2.0 - 1.0);
    float ring = 1.0 - smoothstep(0.0, 0.08, abs(r - 0.86));
    colour = vec4(0.55, 0.68, 0.90, ring * 0.9);    // the accent blue
}
"""


class GalaxyGL(OpenGLFrame):
    """A Tkinter frame that the graphics card draws the galaxy into."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.ctx = None
        self.scene = None
        self.camera = g3d.Camera()
        self.stars = None
        self.notes = None
        self.lines = None
        self.ring = None
        self.light_fbo = None
        # Things given to us before the graphics card connection exists (it's
        # made when the window first appears) wait here, then get sent.
        self.waiting = {}

    # --- Setting up (called by pyopengltk when the frame appears or resizes) ---
    def initgl(self):
        if self.ctx is None:
            self.ctx = moderngl.create_context()
            ctx = self.ctx
            ctx.enable(moderngl.PROGRAM_POINT_SIZE)
            # Older-style OpenGL connections (like the one Tkinter gives us) also
            # need "point sprites" switched on, or shaders can't tell where they
            # are inside a point (gl_PointCoord) and every star looks flat and dim.
            GL.glEnable(0x8861)          # GL_POINT_SPRITE
            self.gas_prog = ctx.program(vertex_shader=GAS_VS, fragment_shader=GAS_FS)
            self.dust_prog = ctx.program(vertex_shader=DUST_VS, fragment_shader=DUST_FS)
            self.sky_prog = ctx.program(vertex_shader=SKY_VS, fragment_shader=SKY_FS)
            self.star_prog = ctx.program(vertex_shader=STAR_VS, fragment_shader=STAR_FS)
            self.tone_prog = ctx.program(vertex_shader=TONE_VS, fragment_shader=TONE_FS)
            self.line_prog = ctx.program(vertex_shader=LINE_VS, fragment_shader=LINE_FS)
            self.ring_prog = ctx.program(vertex_shader=RING_VS, fragment_shader=RING_FS)
            corners = np.array([-1, -1, 3, -1, -1, 3], "f4")        # one big triangle covering the screen
            self.tone_vao = ctx.vertex_array(self.tone_prog, [(ctx.buffer(corners.tobytes()), "2f", "corner")])
            if self.scene is not None:
                self.upload_scene()
            for method, args in self.waiting.items():
                getattr(self, method)(*args)
            self.waiting.clear()
        self.make_light_buffer()

    def make_light_buffer(self):
        """The invisible float picture where light is added up (remade when the size changes)."""
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        if self.light_fbo is not None and self.light_size == (w, h):
            return
        if self.light_fbo is not None:
            self.light_fbo.release()
            self.light_tex.release()
        self.light_tex = self.ctx.texture((w, h), 4, dtype="f2")   # "f2" = numbers that can go above 1
        self.light_fbo = self.ctx.framebuffer(color_attachments=[self.light_tex])
        self.light_size = (w, h)

    # --- Giving it things to draw ---
    def set_scene(self, scene):
        """A new set of ideas: send its points to the graphics card."""
        self.scene = scene
        if self.ctx is not None:
            self.upload_scene()

    def vao(self, program, data, layout, names):
        buffer = self.ctx.buffer(np.ascontiguousarray(data, "f4").tobytes())
        return self.ctx.vertex_array(program, [(buffer, layout, *names)]), buffer

    def upload_scene(self):
        for old in ("gas", "dots", "sky"):
            if getattr(self, old + "_buf", None) is not None:
                getattr(self, old + "_buf").release()
        s = self.scene
        self.gas = self.dots = None
        self.gas_buf = self.dots_buf = None
        if len(s.points):
            gas = np.hstack([s.points, s.light])
            self.gas, self.gas_buf = self.vao(self.gas_prog, gas, "3f 3f", ("pos", "light"))
            self.dust = self.ctx.vertex_array(self.dust_prog, [(self.gas_buf, "3f 3f", "pos", "light")])
        if len(s.dots):
            dots = np.hstack([s.dots, s.dot_light / 255.0])
            self.dots, self.dots_buf = self.vao(self.dust_prog, dots, "3f 3f", ("pos", "light"))
        sky = np.hstack([s.sky, (s.sky_light / 255.0)[:, None]])
        self.sky, self.sky_buf = self.vao(self.sky_prog, sky, "3f 1f", ("dir", "bright"))

    def set_stars(self, positions, tints, brightness, scales, note_positions=None, note_tints=None):
        """The idea stars (and note stars), with their colours, glow and size."""
        if self.ctx is None:
            self.waiting["set_stars"] = (positions, tints, brightness, scales, note_positions, note_tints,)
            return
        for old in (self.stars, self.notes):
            if old is not None:
                old[1].release()
        self.stars = self.notes = None
        if len(positions):
            data = np.hstack([positions, np.asarray(tints) / 255.0,
                              np.asarray(brightness)[:, None], np.asarray(scales)[:, None]])
            self.stars = self.vao(self.star_prog, data, "3f 3f 1f 1f", ("pos", "tint", "bright", "scale"))
        if note_positions is not None and len(note_positions):
            n = len(note_positions)
            # Notes are faint (0.35) so the ideas stay the main stars.
            data = np.hstack([note_positions, np.asarray(note_tints) / 255.0,
                              np.full((n, 1), 0.35), np.ones((n, 1))])
            self.notes = self.vao(self.star_prog, data, "3f 3f 1f 1f", ("pos", "tint", "bright", "scale"))

    def set_lines(self, segments, alphas, colours=None):
        """Constellation lines: `segments` is a list of (point A, point B), each with a colour (0-255)."""
        if self.ctx is None:
            self.waiting["set_lines"] = (segments, alphas, colours)
            return
        if self.lines is not None:
            self.lines[1].release()
        self.lines = None
        if len(segments):
            pts = np.asarray(segments, "f4").reshape(-1, 3)
            if colours is None:
                colours = [(140, 153, 184)] * len(segments)
            tints = np.repeat(np.asarray(colours, "f4") / 255.0, 2, axis=0)
            a = np.repeat(np.asarray(alphas, "f4"), 2)[:, None]
            self.lines = self.vao(self.line_prog, np.hstack([pts, tints, a]), "3f 3f 1f",
                                  ("pos", "tint", "alpha"))

    def set_ring(self, position):
        """The thin circle around the selected star (None = no ring)."""
        if self.ctx is None:
            self.waiting["set_ring"] = (position,)
            return
        if self.ring is not None:
            self.ring[1].release()
        self.ring = None
        if position is not None:
            self.ring = self.vao(self.ring_prog, np.asarray([position], "f4"), "3f", ("pos",))

    # --- Drawing ---
    def draw(self):
        """Draw one frame now (only called when something changed)."""
        if self.ctx is not None and self.winfo_ismapped():
            self._display()           # pyopengltk: make our context current, redraw(), show it

    def uniforms(self, program):
        position, right, up, forward = self.camera.basis()
        w, h = self.light_size
        values = {"cam_pos": position, "cam_right": right, "cam_up": up, "cam_fwd": forward,
                  "screen": (w, h), "focal": g3d.focal_length(w, h)}
        for name, value in values.items():
            if name in program:
                program[name].value = tuple(float(v) for v in np.atleast_1d(value))[0] \
                    if np.ndim(value) == 0 else tuple(float(v) for v in value)

    def redraw(self):
        if self.ctx is None or self.scene is None:
            return
        ctx = self.ctx
        self.make_light_buffer()
        w, h = self.light_size
        # Step 1: add up all the light in the float picture.
        self.light_fbo.use()
        ctx.viewport = (0, 0, w, h)
        ctx.clear(0, 0, 0, 0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE          # "add": light adds up
        for prog in (self.gas_prog, self.dust_prog, self.sky_prog, self.star_prog):
            self.uniforms(prog)
        count = max(30, self.scene.count)
        # Same overall brightness as the old (processor) version; more ideas =
        # more overlapping light, so the exposure goes down as the galaxy grows.
        # More (smaller) gas particles per idea than the old version: each gets
        # a share of the light, so the total brightness stays the same.
        share = 160 / g3d.PARTICLES_PER_IDEA
        self.gas_prog["exposure"].value = 0.094 * share * (30 / count) ** 0.55
        if self.sky is not None:
            self.sky.render(moderngl.POINTS)
        if self.gas is not None:
            self.gas.render(moderngl.POINTS)
            self.dust_prog["strength"].value = 0.10      # gas particles as fine dust...
            self.dust_prog["near_range"].value = 0.35    # ...that only shows up close
            self.dust.render(moderngl.POINTS)
        if self.dots is not None:
            self.dust_prog["strength"].value = 1.0       # the tiny galaxy stars: always
            self.dust_prog["near_range"].value = 0.0
            self.dots.render(moderngl.POINTS)
        if self.notes is not None:
            self.star_prog["base"].value = 0.0011        # notes: much smaller than idea stars
            self.star_prog["min_radius"].value = 0.5
            self.notes[0].render(moderngl.POINTS)
        if self.stars is not None:
            self.star_prog["base"].value = 0.004
            self.star_prog["min_radius"].value = 1.5
            self.stars[0].render(moderngl.POINTS)
        # Step 2: tone map onto the screen.
        ctx.screen.use()
        ctx.viewport = (0, 0, w, h)
        ctx.disable(moderngl.BLEND)
        self.light_tex.use(0)
        self.tone_prog["light"].value = 0
        self.tone_prog["space"].value = tuple(c / 255 for c in g3d.SPACE)
        self.tone_vao.render(moderngl.TRIANGLES)
        # Step 3: lines and the ring on top, normal see-through blending.
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        if self.lines is not None:
            self.uniforms(self.line_prog)
            self.lines[0].render(moderngl.LINES)
        if self.ring is not None:
            self.uniforms(self.ring_prog)
            self.ring[0].render(moderngl.POINTS)
