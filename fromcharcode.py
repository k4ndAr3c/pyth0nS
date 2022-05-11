#!/usr/bin/env python3
import sys

if len(sys.argv) == 1:
    print(f"Use : {sys.argv[0]} <payload>")
    sys.exit(0)

payload = "".join([f"{ord(c)}," for c in sys.argv[1]])
print(f"String.fromCharCode({payload.strip(',')})")
