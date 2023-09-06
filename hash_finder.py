#!/usr/bin/env python
import sys, re
try:
    h = sys.argv[1].lower()
except:
    print("[^] Usage: cat somestrings | {} (md5|sha1|sha256)".format(sys.argv[0]))
    exit(1)

if h == "md5":
    print('\n'.join(re.findall(r'([a-fA-F\d]{32})',sys.stdin.read())))
elif h == "sha1":
    print('\n'.join(re.findall(r'([a-fA-F\d]{40})',sys.stdin.read())))
elif h == "sha256":
    print('\n'.join(re.findall(r'([a-fA-F\d]{64})',sys.stdin.read())))
else:
    print("[^] Usage: cat somestrings | {} (md5|sha1|sha256)".format(sys.argv[0]))
