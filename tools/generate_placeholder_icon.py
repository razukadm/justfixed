"""Generate a placeholder icon (assets/icon.ico) using only Python stdlib.

Run once from repo root:
    python tools/generate_placeholder_icon.py

Produces a 256x256 32-bit BGRA .ico with a dark teal background and white
"JF" block letters. The committed artifact is assets/icon.ico; this script
exists for reproducibility when the placeholder needs to be regenerated.
"""
import struct
from pathlib import Path

BG_COLOR = (0x2C, 0x5F, 0x5D)  # dark teal (R, G, B)
FG_COLOR = (0xFF, 0xFF, 0xFF)  # white

# 5-column x 9-row pixel masks (1 = foreground, 0 = background).
J_MASK = [
    [0, 1, 1, 1, 1],
    [0, 0, 0, 1, 0],
    [0, 0, 0, 1, 0],
    [0, 0, 0, 1, 0],
    [0, 0, 0, 1, 0],
    [0, 0, 0, 1, 0],
    [1, 0, 0, 1, 0],
    [1, 1, 0, 0, 0],
    [0, 1, 1, 0, 0],
]

F_MASK = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 0],
    [1, 1, 1, 1, 0],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 0],
]

SCALE = 8   # pixels per mask cell -> 5*8=40 px wide, 9*8=72 px tall per letter
GAP   = 16  # pixels between J and F
SIZE  = 256


def _make_pixels():
    """Return a flat list of (R, G, B, A) tuples, row 0 = top."""
    pixels = [BG_COLOR + (255,)] * (SIZE * SIZE)

    letter_w = len(J_MASK[0]) * SCALE   # 40
    letter_h = len(J_MASK) * SCALE      # 72
    total_w  = letter_w * 2 + GAP       # 96
    origin_x = (SIZE - total_w) // 2    # 80
    origin_y = (SIZE - letter_h) // 2   # 92

    for mask, off_x in ((J_MASK, 0), (F_MASK, letter_w + GAP)):
        for row, bits in enumerate(mask):
            for col, bit in enumerate(bits):
                if not bit:
                    continue
                px0 = origin_x + off_x + col * SCALE
                py0 = origin_y + row * SCALE
                for dy in range(SCALE):
                    for dx in range(SCALE):
                        idx = (py0 + dy) * SIZE + (px0 + dx)
                        pixels[idx] = FG_COLOR + (255,)

    return pixels


def _write_ico(path: Path, pixels: list) -> None:
    """Write a single 256x256 32-bit BGRA .ico file."""
    # BMP stores rows bottom-to-top; channels are BGRA.
    pixel_data = bytearray()
    for y in range(SIZE - 1, -1, -1):
        for x in range(SIZE):
            r, g, b, a = pixels[y * SIZE + x]
            pixel_data += bytes((b, g, r, a))

    # AND mask: all zeros (fully opaque). Rows are DWORD-aligned.
    row_bytes = ((SIZE + 31) // 32) * 4  # 32 bytes/row for 256px wide
    and_mask  = bytes(row_bytes * SIZE)

    # BITMAPINFOHEADER: biHeight doubled per ICO convention (XOR + AND stacked).
    bmp_info = struct.pack(
        '<IiiHHIIiiII',
        40, SIZE, SIZE * 2, 1, 32, 0, 0, 0, 0, 0, 0,
    )

    image_data = bmp_info + bytes(pixel_data) + and_mask

    # ICONDIR (6 bytes) + ICONDIRENTRY (16 bytes).
    # Width/height of 0 in the entry encodes 256.
    icondir       = struct.pack('<HHH', 0, 1, 1)
    icondir_entry = struct.pack('<BBBBHHII',
                                0, 0, 0, 0, 1, 32,
                                len(image_data), 6 + 16)

    path.write_bytes(icondir + icondir_entry + image_data)
    print(f"Written {len(icondir) + len(icondir_entry) + len(image_data):,} bytes -> {path}")


if __name__ == '__main__':
    out = Path(__file__).parent.parent / 'assets' / 'icon.ico'
    _write_ico(out, _make_pixels())
