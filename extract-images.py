#!/usr/bin/env python3

import argparse
import math
import os
import sys
import typing

from pathlib import Path

import numpy as np

from PIL import Image
from tqdm import trange


COMMON_WIDTHS = (800, 1024, 1152, 1280, 1366, 1440, 1600, 1920, 2048)
COMMON_MODES = ("RGB", "RGBA", "BGRX")


def convert_to_image(data: bytes, width: int, height: int, mode: str) -> Image.Image:
    shape = (height, width, len(mode))

    # Zero pad if necessary
    arr = np.uint8(list(data) + [0] * (math.prod(shape) - len(data)))
    arr = arr.reshape(shape)

    # Reorder channels into normal RGB(A) from specified mode
    split = {c: arr[:, :, i].T for i, c in enumerate(mode)}
    alpha = [split["A"]] if "A" in split else []
    arr = np.array([split["R"], split["G"], split["B"]] + alpha).T

    return Image.fromarray(arr)


def extract_images(fd: typing.BinaryIO, total_size: int, width: int, height: int, mode: str, outdir: Path, nimages: int | None) -> None:
    size = width * height * len(mode)
    if nimages is None:
        nimages = math.ceil(total_size / size)

    # Split data in chunks of size width x height x channels and extract each as a separate image
    print(f"Extracting {nimages} {mode}-image{'s' if nimages > 1 else ''} ({width}x{height})...")
    for i in trange(nimages):
        chunk = fd.read(size)
        img = convert_to_image(chunk, width, height, mode)

        # Skip single-colored images
        if all(minval == maxval for minval, maxval in img.getextrema()):
            continue

        filename = f"{mode}-{width}x{height}" + (f"-{i}" if nimages > 1 else "") + ".png"
        img.save(outdir / filename)


def mode_is_valid(mode):
    # A mode contains R, G, B, A at most once, and any number of Xs
    if not (all(mode.count(c) == 1 for c in "RGB") and mode.count("A") <= 1):
        print("Mode must contain R, G, and B exactly once and A at most once (in any order)")
        return False

    if any(c not in "RGBAX" for c in mode):
        print("Mode can only use R, G, B, and A plus optionally x for padding")
        return False

    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract images from raw data")
    parser.add_argument("infile", type=argparse.FileType("rb"), default=sys.stdin, help="Raw data input file")
    parser.add_argument("--width", type=int, help="Image width")
    parser.add_argument("--height", type=int, help="Image height")
    parser.add_argument("--mode", type=str, help="Image mode within data (e.g. RGB, RGBA, ABGR, BGRx)")
    parser.add_argument("--out", default="output", help="Output directory (default: output/)")
    parser.add_argument("--count", type=int, help="Number of images (max) extracted per setting")
    parser.add_argument("--offset", type=int, default=0, help="Offset in bytes (default: 0)")

    args = parser.parse_args()
    args.widths = (args.width,) if args.width is not None else COMMON_WIDTHS

    args.modes = COMMON_MODES
    if args.mode is not None:
        args.mode = args.mode.upper()
        if not mode_is_valid(args.mode):
            sys.exit(1)
        args.modes = (args.mode,)

    args.out = Path(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    args.infile.seek(0, os.SEEK_END)
    args.length = args.infile.tell() - args.offset
    return args


def main() -> None:
    args = parse_args()

    for width in args.widths:
        for mode in args.modes:
            # Use max possible height if not specified
            height = args.height
            if height is None:
                height = math.ceil(args.length / (width * len(mode)))

            # Extract from provided offset
            args.infile.seek(args.offset)

            extract_images(args.infile, args.length, width, height, mode, args.out, args.count)
            print()


if __name__ == "__main__":
    main()
