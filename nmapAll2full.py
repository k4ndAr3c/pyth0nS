#!/usr/bin/python3
from subprocess import check_output
import sys, re

if len(sys.argv) > 2:
    searchX = True
elif len(sys.argv) == 1:
    print("Usage: {} <target> \optional:<X>".format(sys.argv[0]))
    exit(1)
else:
    searchX = False

target = sys.argv[1]
res = check_output(["nmap", "-Pn", "-sS", "-p-", "--max-retries=50", "-T4", '-oN', "{}-all.nmap".format(target), target])
ports = []
for r in res.split(b'\n'):
    if b"open" in r:
        ports.append(re.findall(b'^[0-9]{1,5}', r)[0])
print(res.decode())

p = b','.join(ports)
full = check_output(["nmap", "-Pn", "-vv", "--script", "vuln", "-A", '-sC', '-sS', '-sV', '-oX', '/tmp/nmap.xml', '-oN', "{}.nmap".format(target), '-p', p, target])
print(full.decode())

if searchX:
    print(check_output(["searchsploit", "-v", "--nmap", "/tmp/nmap.xml"]).decode())

if b"80" in ports:
    if "go" in sys.argv:
        print("[!] gobuster launch ...")
    else:
        answer = input("[?] Launch gobuster against target ? ")
        if answer.lower() != "y":
            exit('Cancel gobuster')
    #dir_list = check_output(["locate", "-r", "directory-list-2.3-medium.txt$"]).split(b'\n')[0].decode()
    dir_list = "/pentest/PeNtEsT/pentestscr1pts/w0Rdl1stS/directory-list-2.3-medium.txt"
    print('Directory list file is {}'.format(dir_list))
    print(check_output(["gobuster", "dir", "-k", "-w", dir_list, "-u", "http://{}/".format(target), "-o", "{}.gobust".format(target)]).decode())
