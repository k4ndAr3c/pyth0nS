#!/usr/bin/env python
from sys import argv

if len(argv) != 3: exit("Usage: %s <find|print> <num>" % argv[0])
if argv[1] == 'print':
    n = int(argv[2])
    r = 0
    for i in range(1, n+1):
        r += i
    print(r)

elif argv[1] == 'find':
    n = int(argv[2])
    r = 0
    c = 0
    for i in range(1, 0xffffffffffffffff+1):
        r += i
        c += 1
        if r == n:
            exit('Secret for {} is {}'.format(n, c))
        if c >= n:
            exit('Not found')
    exit('Not found')
