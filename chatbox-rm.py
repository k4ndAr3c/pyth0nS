#!/usr/bin/env python3
import requests, re, sys, random
from time import sleep

usage = "{} <lang>".format(sys.argv[0])
url = "https://www.root-me.org/?page=news&lang="
if len(sys.argv) != 2:
    exit(usage)

try:
    from googletrans import Translator
except:
    from googletransx import Translator

translator = Translator()
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
    chats = re.findall('<div class="chatbox txs text-(.*?)</p></p></div>\n', r.text, re.DOTALL)
    for _c in chats[::-1]:
        print(_c[12:].replace("\n", " "))
        if sys.argv[1] != "fr" and sys.argv[1] != "en":
            try:
                print(translator.translate(_c[12:], dest="fr").text)
                print("\t===")
            except Exception as e:
                print(e)
    print("-"*42)
    sleep(1)

