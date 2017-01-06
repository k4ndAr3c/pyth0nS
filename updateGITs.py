#!/usr/bin/python2
from os import walk, system
from argparse import ArgumentParser

parser = ArgumentParser(prog='updateGITs.py', usage='./updateGITs.py -p PATH')
parser.add_argument('-p', "--path", type=str, help='Path to gits folder')
args = parser.parse_args()

if args.path:
	paths = []
	path = args.path
	dirs = walk(path).next()[1]
	for dir in dirs:
		paths.append(path + '/' + dir)
	for path in paths:
		system('cd ' + path + ';if [ -d .git ];then echo;echo " [*] Updating $(basename $PWD)";echo;git pull;fi')
else:
	print ' [*] You must input the path to your scripts, i.e /root/scripts'
