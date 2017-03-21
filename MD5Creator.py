#!/usr/bin/env python
import sys, hashlib
print(hashlib.md5(sys.argv[1].strip()).hexdigest())
