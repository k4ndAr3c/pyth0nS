#!/usr/bin/env python3
#coding: utf-8
#auteur:K4ndAr3c

import fnmatch, shutil, errno
import os, random, sys, re
from argparse import ArgumentParser

parser = ArgumentParser(prog='Myrandom.py', usage='Myrandom.py -i PathToMusicDir -o PathToOutDir -n HowMuch')
parser.add_argument('-i', "--indir", type=str, help='Path to music folder')
parser.add_argument('-o', "--outdir", type=str, help='Path to usb')
parser.add_argument('-n', "--num",  type=int, help='How much songs to copy')
args = parser.parse_args()

if args.indir and args.outdir and args.num:
    if args.outdir[-1] == "/":
        od = args.outdir
    else:
        od = args.outdir + "/"
    rootPath = args.indir
    pattern = re.compile(r'.+\.(mp3)$', re.IGNORECASE)
    i=1
    l=[]

    for root, dirs, files in os.walk(rootPath):
        l.extend(os.path.join(root, name) for name in files if pattern.match(name))

    while i<args.num:											
        lo = len(l)
        b = random.randint(0, lo-1)	
        try:
            print("{}> {}".format(i, l[b]))
            if not os.path.exists(od + l[b].split('/')[-1]):
                shutil.copy2(l[b], od)
            else:
                shutil.copy2(l[b], od+l[b].split('/')[-1].replace('.mp3', str(random.randint(0,10000))+".mp3").replace('.MP3', str(random.randint(0,10000))+".MP3"))
            del l[b]
        except Exception as e:
            if e.errno == errno.ENOSPC:
                exit("[-] No Space Left")
            else:
                print('\033[91m'+str(e)+'\033[0m')
        i=i+1	
else:
    parser.print_help()

