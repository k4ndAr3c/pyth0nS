#!/usr/bin/python2
from os import system
from argparse import ArgumentParser
import commands

parser = ArgumentParser(prog='ReCloneGit.py', usage='./ReCloneGit.py -p PATH')
parser.add_argument('-p', "--path", type=str, help='Path to git directory')
args = parser.parse_args()

if args.path:
	path = args.path
        url = commands.getoutput("cat " +path+ ".git/config | grep http | awk '{print $3}'")
	system("rm -vRf "+path+" && git clone "+str(url)+" "+path)
else:
	url = commands.getoutput("cat .git/config | grep http | awk '{print $3}'")
        path = commands.getoutput("pwd")
        system("cd .. ; rm -vRf "+path+" && git clone "+str(url))
