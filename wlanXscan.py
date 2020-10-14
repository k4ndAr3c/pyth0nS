#!/usr/bin/env python3

from subprocess import check_output
import sys, re

r = check_output(["iw", sys.argv[1], "scan"]).decode()
signal = re.findall("signal: (.*.) dBm", r)
ssid =  re.findall("SSID: (.*.)\n", r)

for _ in range(len(signal)):
    print(ssid[_], " => ", float(signal[_])+100, "dBm")
