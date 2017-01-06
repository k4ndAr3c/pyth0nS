#!/usr/bin/python2
import sys,re, hashlib
print hashlib.md5(sys.argv[1].strip()).hexdigest()
