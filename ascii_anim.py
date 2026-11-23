#!/usr/bin/env python3
"""ascii_anim.py — minimal terminal ASCII animator.

An animation is a list of frames; a frame is a block of text (one frame = one
"screen"). Playback just prints frame after frame, moving the cursor back to
the top-left each time (no clearing -> no flicker).

Usage:
  python3 ascii_anim.py demo                      # +  ->  &  ->  @  morph demo
  python3 ascii_anim.py play frames.txt --fps 4   # frames separated by lines of '%'
  python3 ascii_anim.py spin                      # spinner: | / - \\ loop
"""
import argparse
from dataclasses import dataclass
import re
import shutil
import sys
import time
import warnings


@dataclass(frozen=True)
class NormalizedArtwork:
    """An artwork block and the measurements derived from its visible ink."""

    text: str
    width: int
    height: int
    ink: int
    occupancy: float
    footer_detected: bool


_FOOTER_MARKER = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|www\.|copyright|\(c\)|©)",
    re.IGNORECASE,
)


def _trim_empty_border(rows):
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        return []

    left = min(len(row) - len(row.lstrip()) for row in rows if row.strip())
    return [row[left:] for row in rows]


def normalize_artwork(text):
    """Remove transport whitespace and a clearly separated attribution footer."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    pre_cleaned = [row.rstrip() for row in normalized.split("\n")]
    rows = list(pre_cleaned)
    footer_detected = False

    for separator in range(len(rows) - 1, -1, -1):
        if rows[separator].strip():
            continue
        footer_rows = [row for row in rows[separator + 1:] if row.strip()]
        if (footer_rows and len(footer_rows) <= 3
                and all(len(row) <= 60 for row in footer_rows)
                and any(_FOOTER_MARKER.search(row) for row in footer_rows)):
            rows = rows[:separator]
            footer_detected = True
            break

    if footer_detected and not any(not char.isspace() for row in rows for char in row):
        warnings.warn(
            "footer cleanup removed all artwork; restoring the original content",
            UserWarning,
            stacklevel=2,
        )
        rows = list(pre_cleaned)

    rows = _trim_empty_border(rows)
    if not rows:
        return NormalizedArtwork("", 0, 0, 0, 0.0, footer_detected)

    width = max(len(row) for row in rows)
    height = len(rows)
    ink = sum(not char.isspace() for row in rows for char in row)
    occupancy = ink / (width * height) if width and height else 0.0
    return NormalizedArtwork(
        "\n".join(rows), width, height, ink, occupancy, footer_detected
    )


def _center_on_canvas(artwork, width, height):
    if not width or not height:
        return ""
    top = (height - artwork.height) // 2
    left = (width - artwork.width) // 2
    source_rows = artwork.text.split("\n") if artwork.height else []
    rows = [" " * width for _ in range(top)]
    rows.extend(
        " " * left + row + " " * (width - left - len(row))
        for row in source_rows
    )
    rows.extend(" " * width for _ in range(height - len(rows)))
    return "\n".join(rows)


def shared_canvas(text_a, text_b):
    """Normalize two artworks and center both on one common canvas."""
    artwork_a = normalize_artwork(text_a)
    artwork_b = normalize_artwork(text_b)
    width = max(artwork_a.width, artwork_b.width)
    height = max(artwork_a.height, artwork_b.height)
    return (
        _center_on_canvas(artwork_a, width, height),
        _center_on_canvas(artwork_b, width, height),
    )


def dissolve_frames(text_a, text_b, steps=8):
    """Dissolve A into B in a stable, spatially scattered order."""
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("steps must be an integer of at least 1")

    canvas_a, canvas_b = shared_canvas(text_a, text_b)
    rows_a = canvas_a.split("\n") if canvas_a else []
    rows_b = canvas_b.split("\n") if canvas_b else []
    height = len(rows_a)
    width = len(rows_a[0]) if rows_a else 0
    coordinates = sorted(
        ((x, y) for y in range(height) for x in range(width)),
        key=lambda point: (
            ((point[0] * 73856093) ^ (point[1] * 19349663)) & 0xffffffff,
            point[1],
            point[0],
        ),
    )
    percentiles = {
        point: index / (len(coordinates) - 1) if len(coordinates) > 1 else 0
        for index, point in enumerate(coordinates)
    }

    frames = [canvas_a]
    for index in range(1, steps + 1):
        progress = index / (steps + 1)
        output = []
        for y in range(height):
            row = []
            for x in range(width):
                char_a = rows_a[y][x]
                char_b = rows_b[y][x]
                occupied_a = not char_a.isspace()
                occupied_b = not char_b.isspace()
                percentile = percentiles[(x, y)]
                if occupied_a and occupied_b:
                    row.append(char_b if percentile < progress else char_a)
                elif occupied_a:
                    row.append(" " if percentile < progress else char_a)
                elif occupied_b:
                    row.append(char_b if (1 - percentile) < progress else " ")
                else:
                    row.append(" ")
            output.append("".join(row))
        frames.append("\n".join(output))
    frames.append(canvas_b)
    return frames

# ---------------------------------------------------------------------------
# Frame sources
# ---------------------------------------------------------------------------

def demo_frames():
    """The asked-for example: '+' (frame 1) -> '&' (frame 2) -> '@' (frame 3).

    Each frame is the same small grid so the swap reads as a morph at one spot.
    """
    grid = ["    ", "    ", "    ", "    ", "    "]
    def frame(ch):
        g = list(grid)
        g[2] = f"  {ch}  "          # center cell of a 4x5 grid
        return "\n".join(g)
    return [frame("+"), frame("&"), frame("@")]

SPINNER = ["|", "/", "-", "\\"]

def spin_frames():
    def frame(ch):
        g = ["        ", "        ", "        "]
        g[1] = f"   {ch}    "
        return "\n".join(g)
    return [frame(c) for c in SPINNER]

def load_frames(path):
    """Parse a frames file: frames separated by a line containing only '%'."""
    raw = open(path).read()
    return [f.rstrip("\n") for f in raw.split("\n%\n")]


# ---------------------------------------------------------------------------
# Morphing: crossfade two artworks through a character-density ramp
# ---------------------------------------------------------------------------

RAMP = " .,:;-~=+*x#%@"
DENS = {ch: i / (len(RAMP) - 1) for i, ch in enumerate(RAMP)}
# common ASCII-art strokes get sensible densities so real art blends well
DENS.update({"/": 0.45, "\\": 0.45, "|": 0.6, "(": 0.5, ")": 0.5, "_": 0.3,
             "o": 0.55, "O": 0.65, "0": 0.65, ">": 0.5, "<": 0.5, "^": 0.4,
             "v": 0.4, "~": 0.35, '"': 0.3, "!": 0.5, "l": 0.6, "T": 0.6,
             "8": 0.7, "%": 0.8, "$": 0.7, "W": 0.8, "M": 0.8, "B": 0.75})


def _dens(ch):
    return 0.0 if ch.isspace() else DENS.get(ch, 0.5)


def _to_grid(text, rows, cols):
    g = [[" "] * cols for _ in range(rows)]
    for y, line in enumerate(text.splitlines()[:rows]):
        for x, ch in enumerate(line[:cols]):
            g[y][x] = ch
    return g


def _ramp_char(d):
    return RAMP[min(range(len(RAMP)), key=lambda i: abs(DENS[RAMP[i]] - d))]


def _blend(a, b, t):
    out = []
    for ra, rb in zip(a, b):
        row = []
        for ca, cb in zip(ra, rb):
            d = (1 - t) * _dens(ca) + t * _dens(cb)
            row.append(_ramp_char(d))
        out.append("".join(row))
    return "\n".join(out)


def morph_frames(text_a, text_b, steps=3):
    """Frames: A, (steps) blended intermediates, B — reads as a smooth morph."""
    lines_a, lines_b = text_a.splitlines(), text_b.splitlines()
    rows = max(len(lines_a), len(lines_b), 1)
    cols = max(max((len(l) for l in lines_a), default=0),
               max((len(l) for l in lines_b), default=0), 1)
    ga, gb = _to_grid(text_a, rows, cols), _to_grid(text_b, rows, cols)
    frames = ["\n".join("".join(r) for r in ga)]
    for s in range(1, steps + 1):
        frames.append(_blend(ga, gb, s / (steps + 1)))
    frames.append("\n".join("".join(r) for r in gb))
    return frames


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play(frames, fps=4, loops=None, clear=True, out=sys.stdout):
    delay = 1.0 / fps
    n = 0
    while loops is None or n < loops:
        for i, frame in enumerate(frames):
            if clear:
                # ANSI: cursor home, then overwrite — no flicker.
                out.write("\033[H")
            out.write(frame + "\n")
            out.flush()
            time.sleep(delay)
        n += 1
        if clear:
            out.write(f"\nloop {n} done\n")


# ---------------------------------------------------------------------------
# GIF export (frames -> animated GIF via Pillow, if installed)
# ---------------------------------------------------------------------------

def export_gif(frames, path="anim.gif", scale=12, durations=None):
    if durations is None:
        frame_durations = [250] * len(frames)
    elif isinstance(durations, int) and not isinstance(durations, bool):
        if durations <= 0:
            raise ValueError("durations must contain positive integers")
        frame_durations = [durations] * len(frames)
    elif isinstance(durations, list):
        if (len(durations) != len(frames)
                or any(isinstance(value, bool)
                       or not isinstance(value, int)
                       or value <= 0
                       for value in durations)):
            raise ValueError(
                "durations must contain one positive integer per frame"
            )
        frame_durations = durations
    else:
        raise ValueError("durations must be a positive integer or list")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed — skipping GIF export (pip install pillow)")
        return None
    font = ImageFont.load_default()
    # measured via a probe draw so char cells match the font
    bbox = font.getbbox("+")
    char_w = int(bbox[2] - bbox[0]) + 2
    char_h = int(bbox[3] - bbox[1]) + 4
    rows = max(len(f.splitlines()) for f in frames)
    cols = max(max((len(l) for l in f.splitlines()), default=0) for f in frames)
    imgs = []
    for f in frames:
        img = Image.new("RGB", (cols * char_w, rows * char_h), "black")
        d = ImageDraw.Draw(img)
        for y, line in enumerate(f.splitlines()):
            d.text((0, y * char_h), line, fill="lime", font=font)
        imgs.append(img)
    imgs[0].save(
        path,
        save_all=True,
        append_images=imgs[1:],
        duration=frame_durations,
        loop=0,
    )
    return path


def main():
    ap = argparse.ArgumentParser(description="minimal ASCII animator")
    ap.add_argument("mode", choices=["demo", "spin", "play", "gif", "morph"])
    ap.add_argument("file", nargs="?", help="frames file for play/gif, or artwork A for morph")
    ap.add_argument("file_b", nargs="?", help="artwork B for morph mode")
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--loops", type=int, default=None)
    ap.add_argument("--steps", type=int, default=3, help="blended intermediate frames for morph")
    ap.add_argument("--no-clear", action="store_true",
                    help="print frames sequentially (good for piping/recording)")
    ap.add_argument("--out", help="gif output path for gif/morph mode")
    args = ap.parse_args()

    if args.mode == "demo":
        frames = demo_frames()
    elif args.mode == "spin":
        frames = spin_frames()
    elif args.mode == "morph":
        if not (args.file and args.file_b):
            ap.error("morph mode needs two artwork files")
        frames = morph_frames(open(args.file).read().rstrip("\n"),
                              open(args.file_b).read().rstrip("\n"),
                              steps=args.steps)
    else:
        if not args.file:
            ap.error(f"{args.mode} mode needs a frames file")
        frames = load_frames(args.file)

    if args.mode in ("gif", "morph") and args.out:
        path = export_gif(frames, args.out)
        print(f"wrote {path}" if path else "no gif written")
        return

    if args.no_clear:
        for i, f in enumerate(frames):
            print(f"--- frame {i + 1} ---")
            print(f)
        return
    play(frames, fps=args.fps, loops=args.loops, clear=not args.no_clear)


if __name__ == "__main__":
    main()
