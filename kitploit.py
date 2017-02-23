#!/usr/bin/env python2
# -*- coding:Utf-8 -*-

from mechanize import Browser
from BeautifulSoup import BeautifulSoup
#import mechanize, BeautifulSoup

mech = Browser()
url = "http://kitploit.com"
page = mech.open(url)
html = page.read()

soup = BeautifulSoup(html)

h2 = soup.findAll("h2")
for i in h2:
    a = i.findAll("a")
    print a

