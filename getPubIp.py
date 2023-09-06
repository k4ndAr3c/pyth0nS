#!/usr/bin/env python3
import requests
def req_ip():
    r = requests.get("http://ifconfig.me/ip")
    print(r.text)
    return r.text
if __name__ == "__main__":
    req_ip()

### to import, set: sys.path.insert(0, '/root/bin')
