#!/usr/bin/env python

from youtubesearchpython import *
import sys, json, os
COLOR_CODES = {
    'black':    '0;30',     'bright grey':  '0;37',
    'blue':     '0;34',     'white':        '1;37',
    'green':    '0;32',     'bright blue':  '1;34',
    'cyan':     '0;36',     'bright green': '1;32',
    'red':      '0;31',     'bright cyan':  '1;36',
    'purple':   '0;35',     'bright red':   '1;31',
    'yellow':   '1;33',     'bright purple':'1;35',
    'dark grey':'1;30',     'bright yellow':'1;33',
    'normal':   '0'
}

def write_color(text, color, x=True):
    ctext = "\033[" + COLOR_CODES[color] + "m" + text + "\033[0m"
    if x:
        sys.stdout.write(ctext + '\n')
    else:
        sys.stdout.write(ctext + ' ')


maxi = int(sys.argv[2])
customSearch = CustomSearch(sys.argv[1], VideoSortOrder.uploadDate, limit=maxi)
videosSearch = VideosSearch(sys.argv[1], limit=maxi)

lc = json.loads(json.dumps(customSearch.result()))
lv = json.loads(json.dumps(videosSearch.result()))
d = {}
co = 0
#for r in lv["result"]:
#    print(r)

def fill_d(l):
    global d, co
    for _ in range(len(l["result"])):
        title = l["result"][_]["title"]
        if title in d.keys(): pass
        else:
            d[title] = {}
            d[title]["num"] = str(co); co += 1
            try: d[title]["time"] = l["result"][_]["publishedTime"]
            except: d[title]["time"] = "unk title"
            try: d[title]["desc"] = l["result"][_]["descriptionSnippet"][0]["text"]
            except: d[title]["desc"] = "unk desc"
            try: d[title]["url"] = l["result"][_]["link"]
            except: d[title]["url"] = "unk url"
            try: d[title]["chan"] = l["result"][_]["channel"]["name"]
            except: d[title]["chan"] = "unk chan"
            try: d[title]["access"] = l["result"][_]["accessibility"]["title"]
            except: d[title]["access"] = "unk access"

write_color("\n ------- w3lc0m3 fR1en|} ----------\n", "bright blue")

fill_d(lc); fill_d(lv)

for _ in d:
    write_color("{} -> {}".format(d[_]["num"], d[_]["chan"]), "green", False)
    write_color("-> " + _, "yellow", False)
    write_color("-> " + d[_]["time"], "dark grey")
    write_color("     " + d[_]["access"], "white")
    write_color("     " + d[_]["url"], "red")
    write_color("     " + d[_]["desc"], "cyan")
    print()

res = input("Do you want to download a vidz ? ")
if res.isdigit():
    for t in d:
        if res == d[t]["num"]:
            print(d[t]["url"])
            d1r = input('Where ? ')
            if "/" in d1r:
                os.system("cd {} && yt-dlp -f 18 {}".format(d1r, d[t]["url"]))
            else:
                os.system("yt-dlp -f 18 {}".format(d[t]["url"]))




