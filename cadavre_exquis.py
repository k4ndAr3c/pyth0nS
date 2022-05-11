#!/usr/bin/env python3
import os, requests, re, random
#try: from googletransx import Translator
#except: from googletrans import Translator
from essential_generators import DocumentGenerator
gen = DocumentGenerator()
#t = Translator()

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

def gen_s():
    st = ""
    while st == "":
        try:
            s = gen.sentence()
            #st = t.translate(s, dest='fr')
            #return st.text
            st = traduc(s, dest="fr")
            return st
        except Exception as e:
            print(e)
            print('.', end="")

def retr_phrase(nb):
    url = "http://enneagon.org/phrases"
    r = requests.post(url, data={"nb":nb, "submit":"Lancer !"})
    p = re.findall('.*?class="main">\n<p>\n(.*?)\n</p>\n</div>.*?', r.text, re.DOTALL)[0]
    return ' '.join(p.split(" ")[-21:])
    
txt = ""
print("GO!!!")
try:
    sz1 = os.path.getsize('results')
except: sz1 = 0

with open('results', 'a') as f:
    f.write('\n')
    for _ in range(5):
        if random.randint(0, 1000) % 2 == 0:
            a = gen_s()
        else:
            a = retr_phrase(1)
        
        a = a.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
        txt += a + " "
        print("\n> " + ' '.join(a.split(" ")[-3:]))
        f.write(a + " ")
        p = ""
        while p == "":
            p = input(" => ")
        txt += p + " "
        f.write(p + " ")
    f.write('\n')

sz2 = os.path.getsize('results')
if sz2 > sz1:
    os.system('cp results results.svg')
else:
    print("Size check WRONG !")

print("\n"+txt+"\n")
try:
    import pyttsx3
    e = pyttsx3.init()
    e.setProperty('voice', 'french')
    e.setProperty('rate', 135)
    e.say(txt)
    e.runAndWait()
except Exception as e:
    print(e)
