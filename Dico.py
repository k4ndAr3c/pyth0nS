#!/usr/bin/env python3
# -*- coding:Utf-8 -*-

import sys, re
from mechanize import Browser
from bs4 import BeautifulSoup
#import mechanize, BeautifulSoup

r1 = ".*?visionDefinition\">(.*?)</li>*?"
mech = Browser()
url = "http://www.larousse.fr/dictionnaires/francais/"
page = mech.open(url+sys.argv[1].strip())
html = page.read()

soup = BeautifulSoup(html, 'lxml')

li = soup.findAll("li", attrs={'class':'DivisionDefinition'})
for i in li:
    f = re.findall(r1, str(i))
    for j in f:
        print(j.replace('&nbsp', '\n').replace(';: <span class="ExempleDefinition">', 'Ex: ').replace('</span>','')+'\n')
