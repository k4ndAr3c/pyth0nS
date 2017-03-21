#!/usr/bin/env python
import sys, hashlib
print(hashlib.sha1(sys.argv[1].strip()).hexdigest())
