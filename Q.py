#!/usr/bin/python3
import requests, re, os, sys
from mechanize import Browser
from bs4 import BeautifulSoup

url = "https://www.tf1.fr/tmc/quotidien-avec-yann-barthes/videos"
url2 = "https://www.tf1.fr/tmc/quotidien-avec-yann-barthes/videos/replay"
r1 = '.*?href="(.*?).html".*?'

if len(sys.argv) != 3:
    print("[-] Usage: {} <day> <month>".format(sys.argv[0]))

#req = requests.get(url)
#hrefs = re.findall(r1, req.text)
#hrefs = list(set(hrefs))
quotidien = []
os.system('mkdir -p /home/k4ndar3c/Downloads/canal+')

def scrape1page(url):
    html = mech.open(url).read()
    soup = BeautifulSoup(html, 'lxml')
    extract(soup)
    return 0

def extract(soup):
    for h in soup.findAll('a'):
        if "premiere" in str(h) or "deuxieme" in str(h):
            quotidien.append(re.findall(r1, str(h))[0])


mech = Browser()
mech.set_handle_robots(False)

scrape1page(url2)
quotidien = list(set(quotidien))

for e in quotidien:
    if "premiere" in e and "{}-{}".format(sys.argv[1], sys.argv[2]) in e:
        print(e)
        os.system('cd /home/k4ndar3c/Downloads/canal+/ && youtube-dl -f hls-773-1 https://www.tf1.fr{0}.html || youtube-dl -f hls-772-1 https://www.tf1.fr{0}.html'.format(e))
    elif "deuxieme" in e and "{}-{}".format(sys.argv[1], sys.argv[2]) in e:
        print(e)
        os.system('cd /home/k4ndar3c/Downloads/canal+/ && youtube-dl -f hls-772-1 https://www.tf1.fr{}.html'.format(e))

print("[+] Done !:.")

#hls-773-1: premiere
#hls-772-1: deuxieme
