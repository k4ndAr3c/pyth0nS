#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os
if os.path.isfile(sys.argv[1]):
	data = open(sys.argv[1], 'rb').read()
else:
	data = sys.argv[1].encode("latin-1")
out = b''
for d in data:
	out += chr(d-int(sys.argv[2])).encode('latin-1')
print(out)
