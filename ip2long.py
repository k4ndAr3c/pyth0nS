#!/usr/bin/python3
import sys
if sys.argv[1] == "-4":
    l = 0
    IP = sys.argv[2]
    ip = IP.split('.')
    l += int(ip[0]) << 24
    l += int(ip[1]) << 16
    l += int(ip[2]) << 8
    l += int(ip[3])
    print(l)

elif sys.argv[1] == '-6':
    IP = sys.argv[2]
    if "::" in IP:
        ip = IP.split('::')
        base = ip[0].split(":")
        host = ip[1].split(':')
        for i in base:
            l += i
        if host[0] != '':
            for j in range(8-len(base)-len(host)):
                l += "0000"
            for k in host:
                l += k
        else:
            for j in range(8-len(base)):
                l += "0000"
    else:
        for i in IP.split(':'):
            l += i
    print(int(l, 16))

else:
    print('Usage: {} <-4|-6> <ip>'.format(sys.argv[0]))
    exit()

