#!/usr/bin/env python3
import os, re, copy
from sys import argv
from subprocess import check_output
from argparse import ArgumentParser

actions = {
    'start':'start',
    'pause':'pause',
    'resume':'resume',
    'stop':'acpipowerbutton',
    'fstop':'poweroff',
    'reset':'reset',
    'save':'savestate',
    'svc0':"stop",
    'svc1':"start",
    'list':False,
    'listrun':True
    }

class VMman(str):
    def __init__(self, n=-1):
        self.dicvm = {}
        self.vms = b""
        self.headless = True
        self.id = False
        self.num = False
        self.running = copy.deepcopy(self.info('runningvms'))
        self.info('vms')
        if isinstance(n, str) and len(n) > 5:
            self.id = n
        elif int(n) >= 0:
            self.num = int(n)
            self.id = self.dicvm[self.num][0]

    def info(self, x):
        warning = False
        self.vms = check_output(['vboxmanage', 'list', x]).split(b'\n')
        for co, vm in enumerate(self.vms[:-1]):
            if b"WARNING" in vm.upper():
                warning = True
                print("[!]   WARNING! kernel module is not loaded")
            elif re.findall(b'........-....-....-....-............', vm):
                self.dicvm[co] = []
                name = vm.split(b" {")[0].decode()
                ID = vm.split(b' {')[1].replace(b'}', b'').decode().strip()
                self.dicvm[co].append(ID)
                self.dicvm[co].append(name)
        if warning:
            a = False
            r = input('| Do you want to start services ? : ').lower()
            while not a:
                if r == 'y' or r == 'yes':
                    self.svc("start")
                    a = True
                elif r == 'n' or r == 'no':
                    a = True
                    self.show()
                    exit(0)
                else:
                    r = raw_input('| Do you want to start services ? = ').lower()

        return self.dicvm

    def svc(self, x):
        os.system('sudo systemctl {} vboxautostart-service.service vboxballoonctrl-service.service vboxdrv.service vboxweb-service.service'.format(x))

    def show(self, running=False):
        if running:
            to_print = self.running
        else:
            to_print = self.dicvm
        if len(to_print) == 0:
            exit('[-]  No (running) VM')
        print()
        for i in to_print:
            print("{} : {} : {}".format(i, to_print[i][1], to_print[i][0]))

    def choice(self, running=False):
        if running:
            self.show(True)
            d = self.running
        else:
            self.show()
            d = self.dicvm
        resp = int(input("| Choose one :) : "))
        while resp not in d:
            resp = int(input("| Choose one :) = "))
        self.id = d[resp][0]
        self.num = resp

    def start(self, hl='default'):
        if not self.id:
            self.choice()
        if hl == 'default':
            self.ask_headless()
            if self.headless:
                os.system('vboxmanage startvm {} --type headless'.format(self.id))
            else:
                os.system('vboxmanage startvm {}'.format(self.id))
        else:
            if not hl:
                os.system('vboxmanage startvm {}'.format(self.id))
            else:
                os.system('vboxmanage startvm {} --type headless'.format(self.id))

    def ctlvm(self, x):
        if not self.id:
            self.choice(True)
        os.system('vboxmanage controlvm {} {}'.format(self.id, x))

    def ask_headless(self):
        head = input("| Start headless ? : ")
        if head.lower() != "n":
            self.headless = True
        else:
            self.headless = False

    def compact(self):
        hddic = {}
        hdds = check_output(['vboxmanage', 'list', 'hdds'])
        for i, hdd in enumerate(hdds.split(b'\n\n')[:-1]):
            hddic[i] = []
            for v in hdd.split(b'\n'):
                if b'UUID' in v and not b"Parent" in v:
                    hddic[i].append(v.split(b' ')[-1].decode())
                elif b'Location' in v:
                    loc = v.split(b"       ")[1]
                    if os.path.exists(loc):
                        hddic[i].append(loc.decode())
                    else:
                        del hddic[i]
                        i -= 1
            if self.id in hddic[i]:
                print(hddic[i])
                os.system(f"vboxmanage modifymedium disk '{hddic[i][1]}' --compact")
                exit()

        for i, h in hddic.items():
            size = os.path.getsize(hddic[i][1])
            size = size / 1024**3
            print(f"{i} : {h} : {size:.2f}G")
        r = int(input("| Which one ? "))
        while r not in hddic:
            r = int(input("| Which one :) "))
        os.system(f"vboxmanage modifymedium disk '{hddic[r][1]}' --compact")

parser = ArgumentParser(prog=argv[0], usage=f'{argv[0]} <action> -n <num> -i <id> <-H|-S>')
parser.add_argument('action', type=str, help='action to execute', choices=["start", "stop", "fstop", 'reset', "save", 'svc0', 'svc1', 'list', 'listrun', "pause", "resume", "compact"])
group_head = parser.add_mutually_exclusive_group()
group_head.add_argument('-H', "--headless", help='start the vm headless', action='store_true')
group_head.add_argument('-S', "--show", help='start the vm with graphics', action='store_true')
group = parser.add_mutually_exclusive_group()
group.add_argument('-n', "--num", type=str, help='number of the vm (show with list)')
group.add_argument('-i', "--id", type=str, help='id of the vm')
args = parser.parse_args()

if not args.action:
    parser.print_help()

if not args.num and not args.id:
    current = VMman()
elif args.num:
    current = VMman(args.num)
elif args.id:
    current = VMman(args.id)

if args.action in ["listrun","list"]:
    current.show(actions[args.action])
elif args.action in ['svc0', 'svc1']:
    current.svc(actions[args.action])
elif args.action in ["stop", "fstop", 'reset', "save", "pause", "resume"]:
    current.ctlvm(actions[args.action])
elif args.action == "start":
    if args.headless:
        current.start(True)
    elif args.show:
        current.start(False)
    else:
        current.start()
elif args.action == "compact":
    current.compact()



