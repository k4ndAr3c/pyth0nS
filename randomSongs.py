# -*- coding:Utf-8 -*-
#!/usr/bin/env python2
#auteur:K4ndAr3c

import fnmatch, shutil
import os, random, sys, re
from argparse import ArgumentParser

parser = ArgumentParser(prog='Myrandom.py', usage='Myrandom.py -i PathToMusicDir -o PathToOutDir -n HowMuch')
parser.add_argument('-i', "--indir", type=str, help='Path to music folder')
parser.add_argument('-o', "--outdir", type=str, help='Path to usb')
parser.add_argument('-n', "--num",  type=int, help='How much songs to copy')
args = parser.parse_args()

if args.indir and args.outdir and args.num:
	rootPath = args.indir
	pattern = re.compile(r'.+\.(mp3)$', re.IGNORECASE)
	i=1   
	l=[]

	for root, dirs, files in os.walk(rootPath):
		l.extend(os.path.join(root, name) for name in files if pattern.match(name))
		#for filename in fnmatch.filter(files, pattern):
			#l.append(os.path.join(root, filename))

	lo = len(l)
		
	while i<args.num:														
		b = random.randint(1, lo)	
		shutil.copy2(l[b],args.outdir)
	        print "%i> %s" % (i, l[b])
		i=i+1	
else:
	parser.print_help()

