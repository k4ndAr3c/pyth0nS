#!/usr/bin/env python2

import urllib2, mechanize, sys

br = mechanize.Browser()
header = {"Authorization":"Basic OnBhc3M="}
if len(sys.argv) == 1:
    url = 'http://10.42.1.19:8080/requests/status.xml?command=pl_next'
else:
    url = 'http://10.42.1.19:8080/requests/status.xml?command=pl_previous'

req = urllib2.Request(url, None, header)
resp = br.open(req)
