#!/usr/bin/python2
#coding: utf-8
import sys,re
print '\n'.join(re.findall('([\w\.\-]+@[\w\.\-]+)',sys.stdin.read()))
