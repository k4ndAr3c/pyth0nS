#!/usr/bin/env python3
import sys

alias1 = open(sys.argv[1], 'r').read().split("\n")
alias2 = open(sys.argv[2], 'r').read().split("\n")

for a in alias1:
    ok = False
    if "alias " in a:
        testa = a.split('=')[0].split(' ')[1]
        for b in alias2:
            if "alias " in b:
                testb = b.split('=')[0].split(' ')[1]
                if testa == testb:
                    ok = True
                    break
            else: pass
        if not ok:
            print(testa, "=", a)
    elif "function " in a:
        testa = a.split(' ')[1]
        for b in alias2:
            if "function " in b:
                testb = b.split(' ')[1]
                if testa == testb:
                    ok = True
                    break
            else: pass
        if not ok:
            print(testa, "=", a)
