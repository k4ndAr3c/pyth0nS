#!/usr/bin/env python
import sys;print('python -c "eval(compile({},chr(60)+chr(115)+chr(99)+chr(114)+chr(105)+chr(112)+chr(116)+chr(62),chr(101)+chr(120)+chr(101)+chr(99)))"'.format("+".join(["chr({})".format(x) for x in open(sys.argv[1], 'rb').read()])))

#print("+".join([f"chr({ord(x)})" for x in "<script>"]))
#print("+".join([f"chr({ord(x)})" for x in "exec"]))
