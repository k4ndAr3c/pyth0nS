#!/usr/bin/python2
import sys,re
print '\n'.join(re.findall(r'([a-fA-F\d]{32})',sys.stdin.read()))
