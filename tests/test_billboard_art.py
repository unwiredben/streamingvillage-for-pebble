"""Check that billboard cropping preserves the original artwork exactly."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("art", ROOT / "tools/gen_art.py")
art = importlib.util.module_from_spec(spec)
spec.loader.exec_module(art)


def read_png(path):
    data = path.read_bytes()
    offset, compressed = 8, b""
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        tag = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if tag == b"IHDR":
            width, height = struct.unpack_from(">II", body)
        elif tag == b"IDAT":
            compressed += body
        offset += length + 12
    raw = zlib.decompress(compressed)
    stride = width * 4 + 1
    rows = []
    for y in range(height):
        assert raw[y * stride] == 0  # generator uses unfiltered RGBA rows
        row = raw[y * stride + 1:(y + 1) * stride]
        rows.append([tuple(row[x:x + 4]) for x in range(0, width * 4, 4)])
    return width, height, rows


class BillboardArtTest(unittest.TestCase):
    def test_cropped_resource_preserves_original_pixels(self):
        # Reconstruct the original 320-wide artwork independently of gen_billboard.
        original = art.Canvas(320, 122)
        art._billboard(original, 100, art.BB_ACCENT)
        with tempfile.TemporaryDirectory() as directory:
            old_output = art.OUT_DIR
            try:
                art.OUT_DIR = directory
                art.gen_billboard()
            finally:
                art.OUT_DIR = old_output
            width, height, rows = read_png(Path(directory) / "bb_0.png")
        self.assertEqual((width, height), (120, 122))
        for y, row in enumerate(rows):
            self.assertEqual([art.CLEAR] * 100 + row + [art.CLEAR] * 100,
                             original.px[y])
        # The checked-in bitmap must match the generator too.
        self.assertEqual(read_png(ROOT / "resources/images/bb_0.png"),
                         (width, height, rows))


if __name__ == "__main__":
    unittest.main()
