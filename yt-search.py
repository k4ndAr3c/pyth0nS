from youtubesearchpython import *
import sys, json, os
from colorama import *

init()
COLOR_CODES = {
    'black':    Fore.BLACK,     'bright grey':  '0;37',
    'blue':     '0;34',     'white':        Fore.WHITE,
    'green':    Fore.GREEN,     'bright blue':  Fore.BLUE,
    'cyan':     Fore.CYAN,     'bright green': '1;32',
    'red':      Fore.RED,     'bright cyan':  Fore.CYAN,
    'purple':   '0;35',     'bright red':   '1;31',
    'yellow':   Fore.YELLOW,     'bright purple':'1;35',
    'dark grey':Fore.MAGENTA,     'bright yellow':'1;33',
    'normal':   '0'
}

d = {}
co = 0

def write_color(text, color, x=True):
    ctext = COLOR_CODES[color] + text + Fore.RESET
    if x:
        sys.stdout.write(ctext + '\n')
    else:
        sys.stdout.write(ctext + ' ')


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

def main():
    global d, co
    maxi = int(sys.argv[2])
    customSearch = CustomSearch(sys.argv[1], VideoSortOrder.uploadDate, limit=maxi)
    customSearch2 = CustomSearch(sys.argv[1], VideoUploadDateFilter.thisWeek, limit=maxi)
    videosSearch = VideosSearch(sys.argv[1], limit=maxi)
    
    lc = json.loads(json.dumps(customSearch.result()))
    lc2 = json.loads(json.dumps(customSearch2.result()))
    lv = json.loads(json.dumps(videosSearch.result()))
    #for r in lv["result"]:
    #    print(r)

    fill_d(lc)
    fill_d(lv)
    fill_d(lc2)
    
    for _ in d:
        write_color("{} -> {}".format(d[_]["num"], d[_]["chan"]), "green", False)
        write_color("-> " + _, "yellow", False)
        write_color("-> " + d[_]["time"], "dark grey")
        write_color("     " + d[_]["access"], "white")
        write_color("     " + d[_]["url"], "red")
        write_color("     " + d[_]["desc"], "cyan")
        print()
    
    while True:
        res = input("Do you want to download a vidz ? ")
        if res.isdigit():
            for t in d:
                if res == d[t]["num"]:
                    print(d[t]["url"])
                    d1r = input('Where ? ')
                    if "\\" in d1r:
                        os.system("cd {} && yt-dlp -f 18 {}".format(d1r, d[t]["url"]))
                    else:
                        os.system("yt-dlp -f 18 {}".format(d[t]["url"]))
        else: exit(1)

def lookup():
    dones = []
    chans = open("chans.txt", 'r').read().splitlines()
    for c in chans:
        cs = CustomSearch(f"{c}", VideoUploadDateFilter.thisWeek, limit=2)
        d = json.loads(json.dumps(cs.result()))
        for idx in range(len(d['result'])):
            try:
                d = d['result'][idx]
                #print(d)
            except:
                pass
            if d['type'] == "channel":
                continue
            if d['title'] in dones:
                continue
            print(f"[+] Lasts vidz from @{c}")
            try:
                write_color("{} ".format(d["channel"]["name"]), "green", False)
                write_color("-> " + d['title'], "yellow", False)
                write_color("-> " + d["publishedTime"], "dark grey")
                write_color("     " + d["accessibility"]["title"], "white")
                write_color("     " + d["link"], "red")
                write_color("     " + d["descriptionSnippet"][0]["text"], "cyan")
            except Exception as err:
                print(f"[-] {err}")
            dones.append(d['title'])
            print()
            #print("-"*77)





if len(sys.argv) > 1:
    main()
else:
    lookup()



