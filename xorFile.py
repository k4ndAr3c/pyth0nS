#!/usr/bin/env python2
import sys, os
from argparse import ArgumentParser

def xor(s1, s2):
	global key_size
	res = [chr(0)]*key_size
	for i in range(len(s1)):
		q = ord(s1[i])
		d = ord(s2[i])
		k = q ^ d
		res[i] = chr(k)
	res = ''.join(res)
	return res

parser = ArgumentParser(prog='Xor.py', usage='./Xor.py -f FILE -k KEY')
parser.add_argument('-f', "--file", type=str, help='File to xor')
parser.add_argument('-k', "--key", type=str, help='Key')
args = parser.parse_args()

if args.file and args.key:
	with open(args.file, 'rb') as f:
		data = f.read()
	
	key = args.key.strip()
	key_size = len(key)
	dec_data = ''
	
	for i in range(0, len(data), key_size):
		enc = xor(data[i:i+key_size], key)
		dec_data += enc
	with open('xored.out', 'wb') as f:
		f.write(dec_data)
		f.close()
	print "There is sometimes one junk ligne in xored.out"
	print os.system('cat xored.out')
else:
	print "[-] Missing filename or key .."
