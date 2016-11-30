#!/usr/bin/python2
# -*- coding:Utf-8 -*-
#Auteur:k4ndAr3c

from os import system
from argparse import ArgumentParser
import commands

parser = ArgumentParser(prog='ReCloneGit.py', usage='./ReCloneGit.py -p PATH')
parser.add_argument('-p', "--path", type=str, help='Path to git directory')
args = parser.parse_args()

if args.path:
	path = args.path
        url = commands.getoutput("cat " +path+ "/.git/config | grep 'url =' | awk '{print $3}'")
	if "No" in url:
		print " [-] This is not a git repo"
	elif "Aucun" in url:
		print " [-] Ce n'est pas un dépot git"
	else:
		system("rm -vRf "+path+" && git clone "+str(url)+" "+path)
else:
	url = commands.getoutput("cat .git/config | grep 'url ='| awk '{print $3}'")
        path = commands.getoutput("pwd")
	if "No" in url:
        	print " [-] This is not a git repo"
	elif "Aucun" in url:
		print " [-] Ce n'est pas un dépot git"
	else:
		system("cd .. ; rm -vRf "+path+" && git clone "+str(url))
