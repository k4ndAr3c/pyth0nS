#!/usr/bin/env python3
from subprocess import PIPE, Popen
import sys
from time import sleep

green = "\033[92m"
yellow = "\033[93m"

while True:
    p = Popen(['ping', '-c1', '8.8.8.8'], stdout=PIPE, stderr=PIPE).communicate()
    if b"1 received" in p[0]:
        cs = p[0].split(b'time=')[1].split(b" ")[0]
        c = int(cs.split(b".")[0])
        if c <= 84:
            col = green
        elif c > 84:
            col = yellow
        sys.stdout.write(col+"{}\033[34m|\033[0m".format(cs.decode()))
    else:
        sys.stdout.write("\033[31mFAIL.\033[0m")
    sys.stdout.flush()
    sleep(2)
