#!/usr/bin/env python3
import requests, re, sys, random
from time import sleep

usage = "{} <lang> <time_to_sleep>".format(sys.argv[0])
url = "https://www.root-me.org/?page=news&lang="
if len(sys.argv) != 3:
    exit(usage)

def traduc(texte, source="auto", dest="auto"):
    agents = {'User-Agent':"Mozilla/5.0 (X11; Linux x86_64; rv:35.0) Gecko/20100101 Firefox/35.0"}
    link = "http://translate.google.com/m?hl=%s&sl=%s&q=%s" % (dest, source, texte.replace(" ", "+"))
    r = requests.get(link, headers=agents)
    page = r.text

    #print(page)
    avant_traduc = 'class="result-container">'
    result = page[page.find(avant_traduc)+len(avant_traduc):]
    result = result.split("<")[0]
    return result

ua = ['Mozilla/5.0 (Windows NT 6.2; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36',
                                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36',
                                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36',
                                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0.1 Safari/602.2.14',
                                'Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko',
                                'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko',
                                'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)',
                        ]
headers = {'User-Agent':random.choice(ua), 'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'}

for cb in range(9,-1,-3):
    r = requests.get(url+"{}&debut_chat_box_archive={}".format(sys.argv[1], cb), headers=headers)
    chats = re.findall('<div class="chatbox txs text-(.*?)</p></div>', r.text, re.DOTALL)
    for _c in chats[::-1]:
        print(_c[9:].replace("\n", " "))
        if sys.argv[1] != "fr" and sys.argv[1] != "en":
            try:
                print(traduc(_c[9:], dest="fr"))
                print("\t===")
            except Exception as e:
                print(e)
    print("-"*42)
    sleep(int(sys.argv[2]))

