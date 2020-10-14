#!/usr/bin/env python3
#coding: utf-8
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
    lo = len(l)
		
    while i<args.num:											
        b = random.randint(1, lo)	
        try:
            print("{}> {}".format(i, l[b]))
            shutil.copy2(l[b],args.outdir)
        except Exception as e:
            print('\033[91m'+str(e)+'\033[0m')
        i=i+1	
else:
    parser.print_help()

