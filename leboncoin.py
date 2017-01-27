#!/usr/bin/env python2
# encoding: utf-8
import sys, threading
from mechanize import Browser
from argparse import ArgumentParser
from bs4 import BeautifulSoup

def scrape1page(url):
    html = mech.open(url).read()
    soup = BeautifulSoup(html, 'lxml')
    extract(soup)
    return 0

def extractDescription(url):
    #tLock.acquire()
    try:
        html = mech.open(url).read()
        soup = BeautifulSoup(html, 'lxml')
        for div in soup.findAll('div', attrs={"class":"line properties_description"}):
            des = div.find('p', attrs={"itemprop":"description"})
        #tLock.release()
        return '.'.join(des.strings)
    except Exception, e:
        print e
        return "n0ne"

def extract(soup):
    global annonces, co
    for r in soup.findAll('li', attrs={"itemtype":"http://schema.org/Offer"}):
        for i in r.findAll('a'):
            #t = threading.Thread(target=extractDescription, args=(u))
            #t.start()
            annonces['url'].append('http:'+i.get('href'))
            annonces['titre'].append(i.get('title'))
            annonces['des'].append(extractDescription('http:'+i.get('href')))
            
            for j in i.findAll("h3"):
                if j.strings != None:
                    annonces['prix'].append(''.join(j.strings).strip())
                else:
                    annonces['prix'].append("0")

            for l in i.findAll('section', attrs={"class":"item_infos"}):
                for m in l.findAll('p', attrs={"itemprop":"availableAtOrFrom"}):
                    mm = []
                    for n in m.findAll('meta', attrs={"itemprop":"address"}):
                        mm.append(n.get('content').strip())
                    if mm != None:
                        annonces['lieu'].append('.'.join(mm))
                    else:
                        annonces['lieu'].append("0")

                for k in l.findAll('p', attrs={"itemprop":"availabilityStarts"}):
                    if k.string != None:
                        annonces['date'].append(k.string.strip())
                    else:
                        annonces['date'].append("0")

        for v in annonces:
            print annonces[v][co]
        print '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n'
        co += 1
    print "[+]   D0ne:."
    return 0

co = 0
tLock = threading.Lock()
mech = Browser()
mech.set_handle_robots(False)
mech.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc22 Firefox/40.0.1')]
annonces = {}
annonces['titre'] = []
annonces['prix'] = []
annonces['lieu'] = []
annonces['date'] = []
annonces['des'] = []
annonces['url'] = []
parser = ArgumentParser(prog=sys.argv[0])
parser.add_argument('-d', "--departement", type=str, help='Département désiré (sans accent)', default="aveyron")
parser.add_argument('-r', "--region", type=str, help='Région désirée (sans accent)', default="midi_pyrenees")
parser.add_argument('-p', "--prixmax", type=int, help='Prix max désiré', default=300)
parser.add_argument('-n', "--num",  type=int, help='Nombre de pages à visiter', default=1)
parser.add_argument('-t', "--type",  type=str, help='(v)oiture ou (l)ocation', default='v')
args = parser.parse_args()
dept = args.departement.replace("-","_").lower()
region = args.region.replace("-","_").lower()
urllocation = "https://www.leboncoin.fr/locations/offres/"+region+"/"+dept+"/?th=1&parrot=0&mre="+str(args.prixmax)+"&ret=1&ret=2&ret=3&ret=5"
urlvoiture = "https://www.leboncoin.fr/voitures/offres/"+region+"/"+dept+"/?th=1&parrot=0&pe=5&fu=2"
pageCount = 2
urllocation2 = "https://www.leboncoin.fr/locations/offres/"+region+"/"+dept+"/?o="+str(pageCount)+"&parrot=0&mre="+str(args.prixmax)+"&ret=1&ret=2&ret=3&ret=5"
urlvoiture2 = "https://www.leboncoin.fr/voitures/offres/"+region+"/"+dept+"/?o="+str(pageCount)+"&parrot=0&pe=5&fu=2"

if args.type == 'v':
    url = urlvoiture
elif args.type == 'l':
    url = urllocation
else:
    print parser.print_help()
    sys.exit(1)

scrape1page(url)
if args.num > 1:
    for g in range(args.num - 1):
        if args.type == 'v':
            url = urlvoiture2
        elif args.type == 'l':
            url = urllocation2
        scrape1page(url)
        pageCount += 1
