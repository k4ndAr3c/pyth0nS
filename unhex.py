#!/usr/bin/env python2
import sys
print(sys.argv[1].strip().lstrip('0x').decode('hex'))
