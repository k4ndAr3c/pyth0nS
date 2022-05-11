#!/usr/bin/python3
import re, requests, sys
r1 = ".*?<title>(.*.)</title>.*?"
url = b"https://www.youtube.com/watch?v="
u = b"https://youtu.be/"
a=bytes(sys.argv[1].strip(), 'utf-8')
try:
    rep = requests.get(url+a)
    title = re.search(r1, str(rep.text), flags=re.M|re.S).groups()[0]
    if '404' not in title:
        print('[+] Title: '+title)
    else:
        rep = requests.get(u+a)
        title = re.search(r1, str(rep.text), flags=re.M|re.S).groups()[0]
        if '404' not in title:
            print('[+] Title: '+title)
        else:
            print("[-]   Not found:.")
except Exception as e:
    print(e)
