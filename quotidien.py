#!/usr/bin/env python3
import requests, re, os, sys
from mechanize import Browser
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.keys import Keys

url = "https://www.tf1.fr/tmc/quotidien-avec-yann-barthes/videos"
url2 = "https://www.tf1.fr/tmc/quotidien-avec-yann-barthes/videos/replay"
r1 = '.*?href="(.*?).html".*?'
url_login = "https://www.tf1.fr/compte/connexion?redirect="
email = 'zhdgvobq@sharklasers.com'
passwd = 'QSmqGhx5QQBiSJX*'

if len(sys.argv) != 3:
    print("[-] Usage: {} <day> <month>".format(sys.argv[0]))

quotidien = []
#os.system('mkdir -p /home/k4ndar3c/Downloads/canal+')

def scrape1page(url):
    html = mech.open(url).read()
    soup = BeautifulSoup(html, 'lxml')
    extract(soup)
    return 0

def extract(soup):
    for h in soup.findAll('a'):
        if "premiere" in str(h) or "deuxieme" in str(h):
            quotidien.append(re.findall(r1, str(h))[0])

def browseResult(u):
    global browser
    browser = webdriver.Chrome()
    browser.get(u)
    test(passwd, email)

def test(p, e):
    global browser
    q = browser.find_element_by_name('password')
    q.send_keys(p)
    q = browser.find_element_by_name('email')
    q.send_keys(e)
    #print(dir(browser))
    Button = browser.find_element_by_tag_name('Button')
    Button.click()
    #print(browser.page_source)

mech = Browser()
mech.set_handle_robots(False)

scrape1page(url2)
quotidien = list(set(quotidien))

vidz = []
for e in quotidien:
    if "premiere" in e and "{}-{}".format(sys.argv[1], sys.argv[2]) in e:
        print(e)
        vidz.append(e)
    elif "deuxieme" in e and "{}-{}".format(sys.argv[1], sys.argv[2]) in e:
        print(e)
        vidz.append(e)

if 'premiere' in vidz[0]: 
    browseResult(url_login+vidz[0]+'.html')
    input('\t___Press entrer when finish___')
    browseResult(url_login+vidz[1]+'.html')
else: 
    browseResult(url_login+vidz[1]+'.html')
    input('\t___Press entrer when finish___')
    browseResult(url_login+vidz[0]+'.html')





