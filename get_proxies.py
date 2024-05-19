#!/usr/bin/env python3

from requests import get
import json
import socket
from argparse import ArgumentParser
from requests import get
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#original_getaddrinfo = socket.getaddrinfo
#def ipv4_only_getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):     
#    return original_getaddrinfo(host, port, socket.AF_INET, socktype, proto, flags)
#socket.getaddrinfo = ipv4_only_getaddrinfo

protocols = ['socks4', 'socks5']

parser = ArgumentParser()
parser.add_argument('-p', '--protocol', help='Protocol', default="socks")
parser.add_argument('-n', '--num', help='how much', type=int, default=30)
parser.add_argument('-V', "--verify", help='verify proxy', action='store_true')
args = parser.parse_args()
p = args.protocol

def verify(proxy, protocol):
    try:
        #if protocol == 'socks':
        #    proxy = "socks5h://"+proxy.split('//')[1]
        r = get("http://www.google.com", proxies={'http': proxy}, verify=False, timeout=1)
        if r.status_code == 200:
            return True
    except Exception as e:
        if "Max retries exceeded" not in str(e):
            return True
        return False

r = get('https://github.com/proxifly/free-proxy-list/raw/main/proxies/all/data.json').text
pxs = json.loads(r)
proxies = {}

for px in pxs:
    if args.protocol == 'socks':
        if px['protocol'] in protocols and px['anonymity'] == 'transparent':
            proxies[px['proxy']] = []
            proxies[px['proxy']].append(px['protocol'])
            proxies[px['proxy']].append(px['ip'])
            proxies[px['proxy']].append(px['port'])
            proxies[px['proxy']].append(px['score'])
    elif args.protocol == 'http':
        if px['protocol'] == 'http' and px['anonymity'] == 'transparent':
            proxies[px['proxy']] = []
            proxies[px['proxy']].append(px['protocol'])
            proxies[px['proxy']].append(px['ip'])
            proxies[px['proxy']].append(px['port'])
            proxies[px['proxy']].append(px['score'])

proxs = reversed(sorted(proxies, key=lambda x: proxies[x][3]))
co = -1
for p in proxs:
    if co > args.num:
        break
    co += 1
    if args.verify and not verify(p, args.protocol):
        continue
    print(" ".join(map(str, proxies[p][:-1])))


