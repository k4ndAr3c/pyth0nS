#!/usr/bin/python3
#encoding: utf-8

from subprocess import check_output
from time import sleep
import re, sys

if len(sys.argv) == 2: x = True
else: x = False
s = check_output(["whereis", "sensors"]).split()[1]
u = check_output(["whereis", "uptime"]).split()[1]

def doIt():
    a = check_output(s)
    b = b' '.join(check_output(u).split()[-3:]).decode()
    temps = re.findall(b'\ \ \+[0-9]{2}\.[0-9]{1}\xc2\xb0', a)
    for i in temps:
        i = i.decode().strip().replace('+', '')
        if int(i[:2]) >= 70:
            print("\033[91m"+i+"**\033[0m", end='    ')
        elif int(i[:2]) >= 60:
            print("\033[93m"+i+"*\033[0m", end='     ')
        elif int(i[:2]) <= 25:
            print("\033[94m"+i+"\033[0m", end='      ')
        else:
            print("\033[92m"+i+"\033[0m", end='      ')
    print(b)

if not x:
    try:
        while True:
            doIt()
            sleep(1)
    except KeyboardInterrupt:
        exit(0)
else:
    for _i in range(int(sys.argv[1]))[::-1]:
        doIt()
        if _i == 0: exit()
        sleep(1)
