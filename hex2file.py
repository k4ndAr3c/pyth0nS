#!/usr/bin/env python3
from sys import argv
with open(argv[1], 'r') as f:
    h = f.read().strip()
with open(argv[2], 'wb') as f2:
    for _ in range(0, len(h), 2):
        f2.write(chr(int(h[_:_+2], 16)).encode())
print("[+] done !")
