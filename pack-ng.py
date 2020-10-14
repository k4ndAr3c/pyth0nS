#!/usr/bin/env python3
from struct import pack, unpack
import sys

def wx(a):
    return pack("<I", a)

def gx(a):
    return pack("<Q", a)

try:
    x = int(sys.argv[1], 16)

    if len(sys.argv[1]) > 10:
        print("".join('\\x{:02x}'.format(c) for c in gx(x)))
        print(gx(x))
    else:
        print("".join('\\x{:02x}'.format(c) for c in wx(x)))
        print(wx(x))
except:
    x = sys.argv[1]

    if len(sys.argv) > 2:
        for c in reversed(x):
            print("\\x{}".format(hex(ord(c))[2:]), end="")
    else:
        for c in x:
            print("\\x{}".format(hex(ord(c))[2:]), end="")
