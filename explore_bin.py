#!/usr/bin/env python2
import sys
from struct import *

if len(sys.argv) < 3:
    print("[-] Usage: {} <32|64> <file> unhex(bool)".format(sys.argv[0]))
    exit(1)

def db(v):
  return pack("<B", v)

def dw(v):
  return pack("<H", v)

def dd(v):
  return pack("<I", v)

def dq(v):
  return pack("<Q", v)

def rb(v):
  return unpack("<B", v[0])[0]

def rw(v):
  return unpack("<H", v[:2])[0]

def rd(v):
  return unpack("<I", v[:4])[0]

def rq(v):
  return unpack("<Q", v[:8])[0]

dwords = []
gadgets = set()
opcodes = {
    0x8048a2c: ("", None),
    0x8048a20: ("", None),
    0x8048a04: ("", None),
    0x8048930: ("", None),
    0x8048a24: ("", None),
    0x8048a42: ("", None),
    0x80489cc: ("", None),
    0x80489d0: ("", None),
    0x8048a52: ("", None),
    0x80489d4: ("", None),
    0x80483e0: ("", None),
    0x8048a62: ("", None),
    0x8048a72: ("", None),
}

def fun_64(f, uhex=False):
    with open(f, "rb") as fi:
        data = fi.read()

    headers = (0x400000, 0x400000+0x50)
    exec_code = (0x400050, 0x401000)
    data_ref = (0x601000, 0x602000)
    data_ref2 = (0x602000, 0x603000)

    for i in xrange(0, len(data), 8):
        try:
            dwords.append(rq(data[i:i+8]))
        except:
            pass

    for i, d in enumerate(dwords):
        desc = ""
        if exec_code[0] < d < exec_code[1]:
            gadgets.add(d)
            desc = "UNK gadget"
            if d in opcodes and opcodes[d][0]:
                desc = opcodes[d][0]
        elif data_ref[0] < d < data_ref[1]:
            desc = "Child 1"
        elif data_ref2[0] < d < data_ref2[1]:
            desc = "Child 2"
            #gadgets.add(d)
        elif headers[0] < d < headers[1]:
            desc = "@plt ref ?"
	if uhex:
            try:
                print "%4.x -- 0x%.16x: %.16x %s %s" % (i, 0x400000 + i*8, d, desc, hex(d)[2:].decode('hex'))
            except:
                print "%4.x -- 0x%.16x: %.16x %s" % (i, 0x400000 + i*8, d, desc)
	else:
            print "%4.x -- 0x%.16x: %.16x %s" % (i, 0x400000 + i*8, d, desc)

def fun_32(f, uhex=False):
    with open(f, "rb") as fi:
        data = fi.read()

    headers = (0x08048000, 0x08048320-1)
    exec_code = (0x08048320, 0x08049000-1)
    data_ref = (0x08049000, 0x0804a000)

    for i in xrange(0, len(data), 4):
        dwords.append(rd(data[i:i+4]))

    for i, d in enumerate(dwords):
        desc = ""
        if exec_code[0] < d < exec_code[1]:
            gadgets.add(d)
            desc = "UNK gadget"
            if d in opcodes and opcodes[d][0]:
                desc = opcodes[d][0]
        elif data_ref[0] < d < data_ref[1]:
            desc = "data ptr ?"
            #gadgets.add(d)
        elif headers[0] < d < headers[1]:
            desc = "@plt ref ?"
	if uhex:
            try:
                print "%4.x -- 0x%.8x: %.8x %s %s" % (i, 0x08048000 + i*4, d, desc, hex(d)[2:].decode('hex'))
            except:
                print "%4.x -- 0x%.8x: %.8x %s" % (i, 0x08048000 + i*4, d, desc)
	else:
            print "%4.x -- 0x%.8x: %.8x %s" % (i, 0x08048000 + i*4, d, desc)

if len(sys.argv) == 3:
    if sys.argv[1] == "64":
        fun_64(sys.argv[2])
    elif sys.argv[1] == "32":
        fun_32(sys.argv[2])
elif len(sys.argv) == 4 and sys.argv[3] == 'True':
    if sys.argv[1] == "64":
        fun_64(sys.argv[2], True)
    elif sys.argv[1] == "32":
        fun_32(sys.argv[2], True)
elif len(sys.argv) == 4 and sys.argv[3] == 'False':
    if sys.argv[1] == "64":
        fun_64(sys.argv[2])
    elif sys.argv[1] == "32":
        fun_32(sys.argv[2])
else:
    print("[-] Usage: {} <32|64> <file> unhex(bool)".format(sys.argv[0]))



#for g in gadgets:
#    print(hex(g))
