#!/usr/bin/python3
from subprocess import Popen, PIPE, STDOUT, check_output
import sys, re

if len(sys.argv) > 2:
    searchX = True
elif len(sys.argv) == 1:
    print("Usage: {} <target> optional:<X>".format(sys.argv[0]))
    exit(1)
else:
    searchX = False

target = sys.argv[1]

def print_process(cmd):
    process = Popen(
        cmd,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        bufsize=1,
        shell=True
        )
    
    out = []
    for line in process.stdout:
        out.append(line.strip())
        print(line.strip())
    
    process.wait()
    return out

print_process(f"nmap -Pn -sS -v -T4 {target}")
scan = print_process(f"nmap -Pn -sS -p- -v --max-retries=1 -T4 -oN {target}-all.nmap {target}")

ports = []
for r in scan:
    if "open" in r and "Discovered" not in r:
        ports.append(re.findall('^[0-9]{1,5}', r)[0])

p = ','.join(ports)
full = print_process(f"nmap -Pn -vv --script vuln -A -sC -sS -sV -oX /tmp/nmap.xml -oN {target}.nmap -p {p} {target}")

if searchX:
    print(check_output(["searchsploit", "-v", "--nmap", "/tmp/nmap.xml"]).decode())

if "80" in ports:
    if "go" in sys.argv:
        print("[!] gobuster launch ...")
    else:
        answer = input("[?] Launch gobuster against target:80 ? ")
        if answer.lower() != "y":
            exit('Cancel gobuster')
    
    #dir_list = check_output(["locate", "-r", "directory-list-2.3-medium.txt$"]).split(b'\n')[0].decode()
    dir_list = "/pentest/PeNtEsT/pentestscr1pts/w0Rdl1stS/directory-list-2.3-medium.txt"
    print('Directory list file is {}'.format(dir_list))
    print_process(f"gobuster dir -k -w {dir_list} -u http://{target}/ -o {target}.gobust")





