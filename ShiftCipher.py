#!/usr/bin/env python2
import sys, os
if os.path.isfile(sys.argv[1]):
	data = open(sys.argv[1], 'rb').read()
else:
	data = sys.argv[1]
out = ''
for d in data:
	out += chr(ord(d)-int(sys.argv[2]))
print out
