#!/usr/bin/env python2
from PIL import Image
import sys

png = Image.open(sys.argv[1])
png = png.convert('RGB')
width, height = png.size
all_pixels = []
pixels = png.load()

for y in range(height):
    for x in range(width):
        cpixel = pixels[x, y]
        all_pixels.append(cpixel)
print(all_pixels)
