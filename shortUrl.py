#!/usr/bin/env python3
import requests, re, sys
import socks
import socket
import requests

def create_connection(address, timeout=None, source_address=None):
    sock = socks.socksocket()
    sock.connect(address)
    return sock

# Perform DNS resolution through the socket
def getaddrinfo(*args):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (args[0], args[1]))]

socket.getaddrinfo = getaddrinfo
socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5,"10.42.0.1",9100,True)
socket.socket = socks.socksocket
socket.create_connection = create_connection

url = 'https://tinyurl.com/create.php'
r1 = ".*?<div class=\"indent\"><b>(.*?)</b><div id=\"success\">.*?"
rep = requests.post(url, data={'url':sys.argv[1], 'submit':'submit'}).content
tinyurl = re.findall(r1, str(rep))[0]
print('[+]  -> '+tinyurl)
