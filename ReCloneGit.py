#!/usr/bin/python3
# -*- coding:Utf-8 -*-
#Auteur:k4ndAr3c

from os import system
from argparse import ArgumentParser
from subprocess import Popen, PIPE
from os.path import exists

parser = ArgumentParser(prog='ReCloneGit.py', usage='./ReCloneGit.py -p PATH')
parser.add_argument('-p', "--path", type=str, help='Path to git directory')
args = parser.parse_args()

if args.path:
    path = args.path
    if exists(f"{path}/.git/config"):
        url = Popen("cat " +path+ "/.git/config | grep 'url =' | awk '{print $3}'", stdout=PIPE, shell=True).communicate()[0].decode().strip()
        print("[+] Cloning {} => {}".format(url, path))
        system("rm -vRf "+path+" && git clone "+url+" "+path)
    else:
        exit('[-] not a git repo')
else:
    if exists('.git/config'):
        url = Popen("cat .git/config | grep 'url =' | awk '{print $3}'", stdout=PIPE, shell=True).communicate()[0].decode().strip()
        path = Popen("pwd", stdout=PIPE, shell=True).communicate()[0].decode().strip()
        print("[+] Cloning {} => {}".format(url, path))
        system("cd .. ; rm -vRf "+path+" && git clone "+url)
    else:
        exit('[-] not a git repo')
