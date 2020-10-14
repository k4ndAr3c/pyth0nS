#!/usr/bin/python3
from scapy.all import *
from itertools import permutations
from time import sleep
from sys import argv
from subprocess import check_output
import socket

if len(argv) == 1:
    print("[*] Usage {} <lhost> <rhost> <port> <port> .... <port_to_open>".format(argv[0]))
    exit(1)

lhost = argv[1]
rhost = argv[2]
pto = argv[-1]

def sendPkt(ip, port):
    ip = IP(src=lhost, dst=ip)
    SYN = TCP(sport=62345, dport=port, flags="S", seq=12345)
    send(ip/SYN)

def testPort(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((ip, port))
    return result

ports = []
for p in argv[3:-1]:
    ports.append(p)
for x in permutations(ports):
    for port in ports:
        sendPkt(rhost, int(port))
        sleep(1)
    r = testPort(rhost, int(pto))
    sleep(.03)
    if r == 0:
        r = "\033[32mopen :)\033[0m"
    print('[*] testPort: {} => {}'.format(x, r))

print("\n"+"\n".join([x.decode() for x in check_output(["nmap", "-T5", "-p-", "-Pn", rhost]).split(b'\n')[5:]]))
