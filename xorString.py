#!/usr/bin/env python2
# encoding: utf-8
import sys
from itertools import izip, cycle

def xor_crypt_string(data, key):
    xored = ''.join(chr(ord(x) ^ ord(y)) for (x,y) in izip(data, cycle(key)))
    return xored

if len(sys.argv) == 3:
    k = sys.argv[2]
    secret_data = sys.argv[1]
    print xor_crypt_string(secret_data, k)
else:
    print '[-]   {} <text> <key>'.format(sys.argv[0])
