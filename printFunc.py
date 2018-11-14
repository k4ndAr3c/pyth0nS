#!/usr/bin/env python2
from pwn import *
import sys

b1n = ELF(sys.argv[1])
io = b1n.process()

try:
    print "\033[31m[+] ### GOT ###\033[0m"
    for i in b1n.got:
        print i
        print hex(b1n.got[i])
        print ""
except Exception, e:
    print e
try:
    print "\033[31m[+] ### symbols ###\033[0m"
    for i in b1n.symbols:
        print i
        print hex(b1n.symbols[i])
        print ""
except Exception, e:
    print e
try:
    print "\033[31m[+] ### plt ###\033[0m"
    for i in b1n.plt:
        print i
        print hex(b1n.plt[i])
        print ""
except Exception, e:
    print e

