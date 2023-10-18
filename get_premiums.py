#!/usr/bin/env python3
#encoding: utf-8
import requests, re, os, sys
from bs4 import BeautifulSoup
#from html2text import HTML2Text
from time import sleep
from argparse import ArgumentParser

dirs = ["fr/Challenges/App-Systeme", "fr/Challenges/Cracking", "fr/Challenges/Programmation", "fr/Challenges/Cryptanalyse", "fr/Challenges/Steganographie", "fr/Challenges/App-Script", "fr/Challenges/Reseau", "fr/Challenges/Web-Serveur", "fr/Challenges/Web-Client", "fr/Challenges/Realiste", "fr/Challenges/Forensic", "en/Challenges/Cracking", "en/Challenges/App-System", "en/Challenges/Realist", "en/Challenges/App-Script", "en/Challenges/Network", "en/Challenges/Web-Server", "en/Challenges/Cryptanalysis", "en/Challenges/Web-Client", "en/Challenges/Steganography", "en/Challenges/Programming", "en/Challenges/Forensic"]

parser = ArgumentParser(prog=sys.argv[0], usage='{} -s <spip_session>\n\n{}'.format(sys.argv[0], dirs))
parser.add_argument('-s', "--spip", type=str, help='spip_session cookie')
args = parser.parse_args()

spip_session = args.spip
cook = {'spip_session':spip_session, 'spip_admin':"%40kandashaka%40gmail.com"}
user_agent = "Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0"
head = {"User-Agent":user_agent}
base_url = "https://www.root-me.org/"
url = "https://www.root-me.org/k4ndar3c?inc=score&lang="
r1 = '.*?<div class="clearfix"></div>\n<div class="crayon solution-descriptif(.*?)<div class="pagination-centered">.*?'
n429 = 0
S = requests.Session()

def handle_err(res):
    if 'Pour accéder à cette partie du site, veuillez vous authentifier' in res.text or 'To reach this part of the site please login' in res.text: exit('[-] Authentication error ! :(')
    if res.status_code == 429:
        n429 += 1
        if n429 > 5: exit("[-] Too Many Requests :(")
        else:
            print('!{}!'.format(n429), end=" ", flush=True)
            sleep(3)
    if "adresse URL que vous demandez n'existe pas" in res.text: return "Err"
    else: return "OK"

def doIt(chall):
    errors = False
    global rep_svg
    sleep(2)
    print('.', end="", flush=True)
    r = S.get(base_url+chall, cookies=cook, headers=head)
    handle_err(r)
    try:
        s = re.findall('.*? <b>publicly accessible from (.*?)</b>.*?', r.text)[0]
        title = re.findall('.*?itemprop="headline name">(.*?)</h1>.*?', r.text)[0]
        print(chall, s, title)
        with open('premiums_challs', 'a') as f:
            f.write(f'{title}, {s}\n')
    except Exception as e:
        print("[-] {} {}".format(chall, e))
    if errors: return "Err"
    else: return "OK"

if args.spip:
    if os.path.exists('premiums_challs'): os.remove('premiums_challs')
    for lang in ['en']:
        fname = f'/tmp/kanda_base_page_rm_{lang}'
        if os.path.exists(fname) and os.path.getsize(fname) != 0:
            with open(fname, 'r') as f:
                html = f.read()
        else:
            page = requests.get(url+lang, headers=head)
            if page.status_code == 200:
                html = page.text
                with open(fname, 'w') as f:
                    f.write(html)
            else:
                exit(f"[-] Error in get base page {lang} ({page.status_code})")
        
        soup = BeautifulSoup(html, features="lxml")
        red_chall = []
        li = soup.findAll("li")
        for i in li:
            a = i.findAll("a")
            if 'rouge' in str(a):
                u = re.findall('.*? href="(.*?)" title.*?', str(a))[0]
                red_chall.append(u)
        
        for chall in red_chall:
            z = doIt(chall)
            if z == "Err":
                sleep(3)
                z = doIt(chall)
                if z == "Err":
                    print('\033[31m[!][!] Error: {}\033[0m'.format(chall))
        
else:
    parser.print_help()
