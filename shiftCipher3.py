#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os
if os.path.isfile(sys.argv[1]):
	data = open(sys.argv[1], 'r').read()
else:
	data = sys.argv[1]
out = ''
for d in data:
	out += chr(ord(d)-int(sys.argv[2]))
print(out)
