#!/usr/bin/env python3
# encoding:utf-8
import socks, subprocess
import urllib, threading
import sys, socket, time, base64, os, hashlib, random
import requests, re, zlib

COLOR_CODES = {
    'black':    '0;30',     'bright grey':  '0;37',
    'blue':     '0;34',     'white':        '1;37',
    'green':    '0;32',     'bright blue':  '1;34',
    'cyan':     '0;36',     'bright green': '1;32',
    'red':      '0;31',     'bright cyan':  '1;36',
    'purple':   '0;35',     'bright red':   '1;31',
    'yellow':   '0;33',     'bright purple':'1;35',
    'dark grey':'1;30',     'bright yellow':'1;33',
    'normal':   '0'
}
def write_color(text, color):
    ctext = "\033[" + COLOR_CODES[color] + "m" + text + "\033[0m"
    sys.stdout.write(ctext + '\n')
def connectTor():
    socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5,"10.42.0.1",9100,True)
    socket.socket = socks.socksocket
    write_color("[+]   Connect to TOR", 'green')

IDENT = NICK = "P13rre"
REALNAME = 'Pierre'
CHAN = "#root-me_challenge"
chServ = "irc.root-me.org"
PASSWORD = ""
data = ''
CMD = sys.argv[1]
if len(sys.argv) < 2:
    print("[-] Usage: {} <CMD> <arg>".format(sys.argv[0]))
    exit(1)
try:
    arg = sys.argv[2]
except:
    if "chall" not in CMD:
        arg = "k4ndar3c"
    else:
        arg = ""

if 'tor' in sys.argv:connectTor()
write_color('[+]   Start to connect.', 'blue')
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((chServ, 6667))
s.send(bytes("NICK {}\r\n".format(NICK), 'utf-8'))
s.send(bytes("USER {} {} {} :py\r\n".format(NICK, IDENT, REALNAME), 'utf-8'))
write_color('[+]   Connection established.', 'green')
def mess2chan(mes):
    global s, fileout
    s.send(bytes('PRIVMSG {} :{} \r\n'.format(CHAN, mes), 'utf-8'))
    write_color('[+]   Bot says: {}'.format(mes), 'bright grey')

ping = 0
try:
    while True:
        data = s.recv(4096)
        #try:
        #    print(data.decode('utf-8'))
        #except:
        #    print(data)
        if data.find(b'PING') != -1:
            ping += 1
            s.send(bytes("PONG {}\r\n".format(data.split()[1].decode()), 'utf-8'))
        if data.find(b'001') != -1:
            s.send(bytes("JOIN {}\r\n".format(CHAN), 'utf-8'))
            time.sleep(2)
        if data.find(b'376') != -1:
            time.sleep(5)
            s.send(bytes("PRIVMSG BotInfo :!{} {}\r\n".format(CMD, arg), 'utf-8'))
            time.sleep(2)
            tmp = s.recv(4096)
            if b"User not found" in tmp:
              print(re.findall(b'.*?PRIVMSG P13rre(.*.)\r\n.*?', tmp)[1].replace(b'\x02\x03',b'').replace(b'\x0312\x02',b'').replace(b'\xc2\xa0',b'')[2:].replace(b'|',b'\n').decode('utf-8'))
            else:
              print(re.findall(b'.*?PRIVMSG P13rre(.*.)\r\n.*?', tmp)[0].replace(b'\x02\x03',b'').replace(b'\x0312\x02',b'').replace(b'\xc2\xa0',b'')[2:].replace(b'|',b'\n').decode('utf-8'))
            s.send(bytes("QUIT {}\r\n".format(CHAN), 'utf-8'))
            time.sleep(2)
            exit(0)


except KeyboardInterrupt:
    s.send(bytes("QUIT {}\r\n".format(CHAN), 'utf-8'))
    write_color("[+]   Everything closed.", 'cyan')
