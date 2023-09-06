#!/usr/bin/env python3

from sys import argv
from base64 import b64decode, b64encode

toks = argv[1].split('.')
for i in toks:
    tok = i.replace('-', '+').replace('_', '/')
    while len(tok) % 4 != 0:
        tok += '='
    tok = b64decode(tok.encode())
    print(tok)

