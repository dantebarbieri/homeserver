#!/usr/bin/env python3
"""Draws the Ghibli fastfetch logos.

Each logo is a small pixel image (shapes plus a hand-drawn face) that is
rendered with half blocks, so every terminal cell shows two square pixels.
Colours are xterm-256, not truecolor: Apple's Terminal.app can't do truecolor.

    python3 generate.py            write the .ansi files next to this script
    python3 generate.py --check    fail if the committed files are stale

fastfetch loads them with `--logo <file> --logo-type file-raw`.
"""
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def blank(w, h):
    return [[None] * w for _ in range(h)]


def inside_edge_distance(mask):
    """Distance from each filled pixel to the nearest empty pixel (or the edge)."""
    h, w = len(mask), len(mask[0])
    empties = [(x, y) for y in range(h) for x in range(w) if not mask[y][x]]
    out = {}
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            d = min(x + 1, y + 1, w - x, h - y)
            for ex, ey in empties:
                d = min(d, math.hypot(x - ex, y - ey))
            out[(x, y)] = d
    return out


def capsule(x, y, bx, by, ax, ay, r0):
    """Inside a tapered capsule running from base B (radius r0) to apex A (radius 0)."""
    dx, dy = ax - bx, ay - by
    s = max(0.0, min(1.0, ((x - bx) * dx + (y - by) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (bx + s * dx), y - (by + s * dy)) <= r0 * (1 - s)


def overlay(img, art, palette, x0, y0):
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            if ch != ".":
                img[y0 + dy][x0 + dx] = palette[ch]


def render(img):
    """Pixel rows -> ANSI text, two pixel rows per terminal row."""
    if len(img) % 2:
        img = img + [[None] * len(img[0])]
    lines = []
    for y in range(0, len(img), 2):
        line, state = [], (None, None)
        for top, bot in zip(img[y], img[y + 1]):
            if top is None and bot is None:
                ch, want = " ", (None, None)
            elif bot is None:
                ch, want = "▀", (top, None)
            elif top is None:
                ch, want = "▄", (bot, None)
            elif top == bot:
                ch, want = "█", (top, None)
            else:
                ch, want = "▀", (top, bot)
            if ch == " " and state[1] is None:
                want = state
            if want != state:
                seq = "\x1b[0m"
                if want[0] is not None:
                    seq += f"\x1b[38;5;{want[0]}m"
                if want[1] is not None:
                    seq += f"\x1b[48;5;{want[1]}m"
                line.append(seq)
                state = want
            line.append(ch)
        line.append("\x1b[0m")
        lines.append("".join(line).rstrip(" "))
    return "\n".join(lines) + "\n"


def calcifer():
    w, h = 31, 30
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            px, py = x + 0.5, y + 0.5
            body = abs((px - 15.5) / 14.0) ** 2.6 + abs((py - 20.5) / 9.5) ** 2.6 <= 1
            mask[y][x] = (
                body
                or capsule(px, py, 15, 17, 19.5, 0.5, 8.5)
                or capsule(px, py, 6.5, 20, 2.5, 8, 4.8)
                or capsule(px, py, 24.5, 19, 28.5, 6, 4.6)
            )
    dist = inside_edge_distance(mask)
    flame = [(1.4, 196), (2.6, 208), (3.8, 214), (5.0, 220), (99, 227)]
    img = blank(w, h)
    for (x, y), d in dist.items():
        img[y][x] = next(c for lim, c in flame if d < lim)

    face = {"F": 202, "f": 208, "W": 255, "K": 16, "M": 88}
    overlay(img, [
        "....fffffffffff....",
        "..ffFFFFFFFFFFFff..",
        ".fFFFFFFFFFFFFFFFf.",
        "FFFFFFFFFFFFFFFFFFF",
        "FFFWWWFFFFFFFWWWFFF",
        "FFFWKWFFFFFFFWKWFFF",
        "FFFWKWFFFFFFFWKWFFF",
        "FFFFFFFFFFFFFFFFFFF",
        "FMMMMMMMMMMMMMMMMMF",
        "FFMMMMMMMMMMMMMMMFF",
        "FFFMMMMMMMMMMMMMFFF",
        "FFFFFMMMMMMMMMFFFFF",
        "..FFFFFFFFFFFFFFF..",
        "....FFFFFFFFFFF....",
    ], face, 6, 12)
    return render(img)


def no_face():
    w, h = 30, 40
    mask = [[False] * w for _ in range(h)]
    img = blank(w, h)
    cx = 14.5
    for y in range(h):
        for x in range(w):
            px, py = x + 0.5, y + 0.5
            head = ((px - cx) / 8.7) ** 2 + ((py - 11.5) / 11.0) ** 2 <= 1
            t = (py - 14) / 25.0
            half = 8.0 + 2.5 * (1 - math.exp(-t * 7)) + 3.5 * t ** 1.6
            robe = 0 <= t <= 1 and abs(px - cx) <= half
            mask[y][x] = head or robe
    dist = inside_edge_distance(mask)
    for (x, y), d in dist.items():
        fold = y > 22 and min(abs(x - cx - o) for o in (-5.5, 0.5, 6.5)) < 0.6
        shade = 238 if fold else 236 if x < 14 else 237
        img[y][x] = 244 if d < 1.3 else 241 if d < 2.2 else shade

    face = {"W": 255, "w": 252, "K": 16, "P": 134}
    overlay(img, [
        "...wWWWWWWw...",
        "..wWWWWWWWWw..",
        ".wWWWWWWWWWWw.",
        ".WPPPPWWPPPPW.",
        ".WWKKWWWWKKWW.",
        ".WKKKKWWKKKKW.",
        ".WPPPPWWPPPPW.",
        ".WWWWWWWWWWWW.",
        ".WWWWWWWWWWWW.",
        ".WWWWWKKWWWWW.",
        ".WWWWKKKKWWWW.",
        ".WWWWKKKKWWWW.",
        ".WWWWWKKWWWWW.",
        "..wWWWWWWWWw..",
        "...wWWWWWWw...",
        "....wwwwww....",
    ], face, 8, 3)
    return render(img)


LOGOS = {"calcifer": calcifer, "no-face": no_face}


def main():
    stale = False
    for name, draw in LOGOS.items():
        path = HERE / f"{name}.ansi"
        text = draw()
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(f"stale: {path.name}", file=sys.stderr)
                stale = True
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(path)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
