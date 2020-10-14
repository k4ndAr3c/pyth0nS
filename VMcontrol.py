#!/usr/bin/python2
#encoding: utf-8
import os, sys, re
from subprocess import check_output

def info(x):
    global dicvm
    warning = False
    vms = check_output(['vboxmanage', 'list', x]).split('\n')
    dicvm = {}
    co = 0
    for vm in vms[:-1]:
        if "WARNING" in vm.upper():
            warning = True
            print("[!]   WARNING! kernel module is not loaded")
        elif re.findall('........-....-....-....-............', vm):
            dicvm[co] = []
            name = vm.split(" {")[0]
            ID = vm.split(' {')[1].replace('}', '')
            dicvm[co].append(ID)
            dicvm[co].append(name)
            co += 1
    if warning:
        a = False
        r = raw_input('| Do you want to start services ? : ').lower()
        while not a:
            if r == 'y' or r == 'yes':
                svc("start")
                a = True
            elif r == 'n' or r == 'no':
                a = True
                show()
                exit(0)
            else:
                r = raw_input('| Do you want to start services ? = ').lower()

def svc(x):
    os.system('sudo systemctl {} vboxautostart-service.service vboxballoonctrl-service.service vboxdrv.service vboxweb-service.service'.format(x))

def show():
    global dicvm
    if len(dicvm) == 0:
        exit('[-]   No (running) VM')
    for i in dicvm:
        print("{} : {} : {}".format(i, dicvm[i][1], dicvm[i][0]))

def choice():
    resp = raw_input("| Choose one :) : ")
    while int(resp) not in dicvm:
        resp = raw_input("| Choose one :) = ")
    return resp

def start(ID, b):
    if b:
        os.system('vboxmanage startvm {} --type headless'.format(ID))
    else:
        os.system('vboxmanage startvm {}'.format(ID))

def ctlvm(ID, x):
    os.system('vboxmanage controlvm {} {}'.format(ID, x))

def usage():
    print("[-]   Usage: {0} <start|stop|fstop|reset|save> \option<id>\n   else: {0} <svc0|svc1||list|listrun>".format(sys.argv[0]))
    exit(1)

if len(sys.argv) == 1:
    usage()

if sys.argv[1] == 'svc0':
    svc("stop")
    exit(0)
elif sys.argv[1] == 'svc1':
    svc("start")
    exit(0)
elif sys.argv[1] == 'list':
    info("vms")
    show()
    exit(0)
elif sys.argv[1] == 'listrun':
    info("runningvms")
    show()
    exit(0)
elif sys.argv[1] not in ['svc0', 'svc1', 'list', "start", "stop", "fstop", 'listrun', 'reset', "save"]:
    usage()

info("vms")
present = False
if len(sys.argv) == 3:
    for i in dicvm:
        if sys.argv[2] == dicvm[i][0]:
            present = True
            if sys.argv[1].lower() == "start":
                head = raw_input("| Start headless ? : ")
                if head.lower() != "n":
                    start(sys.argv[2], True)
                else:
                    start(sys.argv[2], False)
            elif sys.argv[1].lower() == "stop":
                ctlvm(sys.argv[2], "acpipowerbutton")
            elif sys.argv[1].lower() == "fstop":
                ctlvm(sys.argv[2], "poweroff")
            elif sys.argv[1].lower() == "reset":
                ctlvm(sys.argv[2], "reset")
            elif sys.argv[1].lower() == "save":
                ctlvm(sys.argv[2], "savestate")
    if not present:
        print("[-]   ID incorrect !:.")
        show()
        exit(1)

elif len(sys.argv) == 2:
    if "stop" in sys.argv[1].lower() or "reset" in sys.argv[1].lower() or "save" in sys.argv[1].lower():
        info("runningvms")
        show()
    else:
        show()
    c = choice()
    for i in dicvm:
        if c == str(i):
            present = True
            if sys.argv[1].lower() == "start":
                head = raw_input("| Start headless ? : ")
                if head.lower() != "n":
                    start(dicvm[int(c)][0], True)
                else:
                    start(dicvm[int(c)][0], False)
            elif sys.argv[1].lower() == "stop":
                ctlvm(dicvm[int(c)][0], "acpipowerbutton")
            elif sys.argv[1].lower() == "fstop":
                ctlvm(dicvm[int(c)][0], "poweroff")
            elif sys.argv[1].lower() == "reset":
                ctlvm(dicvm[int(c)][0], "reset")
            elif sys.argv[1].lower() == "save":
                ctlvm(dicvm[int(c)][0], "savestate")
    if not present:
        print("[-]   ID incorrect !:.")
        show()
        exit(1)
