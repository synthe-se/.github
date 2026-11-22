# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools[woff]", "uharfbuzz"]
# ///
"""Builds the profile's pictures: the banner (light and dark) and one
signature per project, the same additive synthesis as synthe.se
(src/lib/signature.ts): the name seeds the partials.

    uv run tools/build-assets.py path/to/Fraunces-VF.woff2 path/to/synthese

Text is drawn as outlines, so the pictures carry no font.
"""

import io
import math
import re
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).resolve().parent.parent / "profile" / "assets"
PROJECTS = ["maison", "clapier", "synthboard", "uniseal", "frame-kernel"]

THEMES = {
    "light": {"ink": "#1B222C", "muted": "#525A66", "accent": "#0E5E68", "soft": "#4E8A92", "hum": ".45"},
    "dark": {"ink": "#EAE7E0", "muted": "#A8AEB8", "accent": "#63C0CB", "soft": "#3E7A84", "hum": ".55"},
}
# readable on GitHub's light and dark grounds alike
SIG_STROKE = "#4E8A92"

SIG_W, SIG_H = 160, 28


def imul(a: int, b: int) -> int:
    return (a * b) & 0xFFFFFFFF


def sig_path(name: str) -> str:
    h = 2166136261
    for ch in name:
        h = imul(h ^ ord(ch), 16777619)
    seed = h

    def r() -> float:
        nonlocal seed
        seed = (imul(seed, 1664525) + 1013904223) & 0xFFFFFFFF
        return seed / 4294967296

    partials = [1 + math.floor(r() * 2), 2 + math.floor(r() * 3), 5 + math.floor(r() * 4)]
    amps = [0.5 + r() * 0.4, 0.25 + r() * 0.3, 0.12 + r() * 0.2]
    phases = [r() * 6.2832, r() * 6.2832, r() * 6.2832]
    pts = []
    for x in range(0, SIG_W + 1, 4):
        u = x / SIG_W
        win = math.sin(math.pi * u) ** 2
        y = sum(amps[k] * math.sin(u * partials[k] * 6.2832 + phases[k]) for k in range(3))
        pts.append(f"{x},{SIG_H / 2 + y * win * (SIG_H / 2.4):.1f}")
    return "M" + "L".join(pts)


def outline(font_path: str, text: str, size: float, wght: int, opsz: int) -> tuple[str, float, float]:
    """The text as one SVG path, baseline at y=0, and where its ink starts and ends."""
    font = TTFont(font_path)
    wanted = {"wght": wght, "opsz": opsz, "SOFT": 0, "WONK": 0}
    # a variable file carries some of these axes, seldom all: pin the ones it has
    font = instantiateVariableFont(
        font, {a.axisTag: wanted.get(a.axisTag, a.defaultValue) for a in font["fvar"].axes}
    )
    buf = io.BytesIO()
    font.flavor = None
    font.save(buf)
    hb_font = hb.Font(hb.Face(buf.getvalue()))
    hbuf = hb.Buffer()
    hbuf.add_str(text)
    hbuf.guess_segment_properties()
    hb.shape(hb_font, hbuf)
    scale = size / font["head"].unitsPerEm
    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    ink = BoundsPen(glyphs)
    x = 0.0
    for info, pos in zip(hbuf.glyph_infos, hbuf.glyph_positions):
        t = (scale, 0, 0, -scale, (x + pos.x_offset) * scale, -pos.y_offset * scale)
        glyphs[order[info.codepoint]].draw(TransformPen(pen, t))
        glyphs[order[info.codepoint]].draw(TransformPen(ink, t))
        x += pos.x_advance
    return pen.getCommands(), ink.bounds[0], ink.bounds[2]


# the S in its 128 box: where its ink starts and ends, round caps included
MARK_INK = (26.25, 101.75)


def banner(font_path: str, mark_paths: list[str], theme: dict) -> str:
    """The word and the line are centred on their ink and share one axis."""
    W, H = 880, 176
    word, word_l, word_r = outline(font_path, "Synthèse", 76, 600, 144)
    line, line_l, line_r = outline(font_path, "Build, host, measure.", 25, 400, 30)
    k = 92 / 128
    mark_l, mark_r = MARK_INK[0] * k, MARK_INK[1] * k
    gap = 20
    # the word sits on the picture's axis, over the line; the S hangs to its left
    word_x = W / 2 - (word_l + word_r) / 2
    mark_x = word_x + word_l - gap - mark_r
    line_x = (W - (line_r - line_l)) / 2 - line_l
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" fill="none" role="img" aria-label="Synthèse. Build, host, measure.">
  <g transform="translate({mark_x:.1f} 14) scale({k:.4f})" stroke="{theme['accent']}">
    <g stroke="{theme['soft']}" opacity="{theme['hum']}">
      <path d="{mark_paths[0]}" stroke-width="3.5"/>
      <path d="{mark_paths[1]}" stroke-width="2.5"/>
    </g>
    <path d="{mark_paths[2]}" stroke-width="13.5" stroke-linecap="round"/>
  </g>
  <path transform="translate({word_x:.1f} 86)" d="{word}" fill="{theme['ink']}"/>
  <path transform="translate({line_x:.1f} 150)" d="{line}" fill="{theme['muted']}"/>
</svg>
"""


def main() -> None:
    font_path, site = sys.argv[1], Path(sys.argv[2])
    mark_src = (site / "src/components/Mark.astro").read_text()
    mark_paths = re.findall(r'<path class="[hf]" d="([^"]+)"', mark_src)
    assert len(mark_paths) == 3, "the S mark: three paths expected"
    OUT.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        (OUT / f"banner-{name}.svg").write_text(banner(font_path, mark_paths, theme))
    for name in PROJECTS:
        (OUT / f"sig-{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIG_W} {SIG_H}" '
            f'width="{SIG_W}" height="{SIG_H}" fill="none" aria-hidden="true">'
            f'<path d="{sig_path(name)}" stroke="{SIG_STROKE}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>\n'
        )


main()
