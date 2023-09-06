#!/usr/bin/env python
import requests, json, os, sys

api_link = 'https://api.www.root-me.org'
headers = { "User-Agent" : "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:87.0) Gecko/20100101 Firefox/87.0" }
if len(sys.argv) == 2:
    login = sys.argv[1]
else:
    login = "kandashaka"
passwd = os.getenv('P4SSW0RD')
if passwd == '' or passwd == None:
    exit("[-] Must provide P4SSW0RD env variable")
r = requests.post(api_link + "/login", data={"login":login, "password":passwd}, headers=headers)
if r.status_code != 200: print('An error occured (HTTP %d)' % r.status_code)
else:
    response = json.loads(r.content)[0]
    if 'info' in response.keys():
        if "spip_session" in response['info'].keys() and response['info']['code'] == 200:
            cookies = {"spip_session": response['info']["spip_session"]}
            print("[+] Connected, {}".format(json.dumps(cookies)))
            with open('/tmp/rootme.cookies', "w") as f:
                f.write(json.dumps(cookies))
