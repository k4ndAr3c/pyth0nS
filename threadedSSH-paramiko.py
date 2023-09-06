#!/usr/bin/python3

import queue
import time
import threading, sys
import subprocess, paramiko

class WorkerThreads(threading.Thread):

    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.queue = queue
        
    def run(self):
        global CMD
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.load_host_keys("/root/.ssh/known_hosts")
        while True:
            counter = self.queue.get()
            try:
                ssh.connect(counter.decode())
            except:
                print('[-] Failed to connect with {}\n'.format(counter.decode()))
            else:
                stdin, stdout, stderr = ssh.exec_command(CMD)
                print("\t.:| {} |:.".format(counter.decode()))
                for line in stdout.readlines():
                    print(line.strip())
                print("\n")
            ssh.close()
            self.queue.task_done()

l = subprocess.check_output(['arp-scan', '-l']).split(b'\n')
CMD = str(sys.argv[1])
hosts = l[2:-4]
ips = []
macs = []
excludes = [b"10.42.1.100", b"10.42.1.3", b"10.42.1.37", b"10.42.1.55"]

for a in hosts:
	ip, mac, mark = a.split(b'\t')
	if ip not in excludes:
		ips.append(ip)
		macs.append(mac)

queue = queue.Queue()

for i in range(len(ips)):
	worker = WorkerThreads(queue)
	worker.setDaemon(True)
	worker.start()

for j in ips:
	queue.put(j)

queue.join()

print("Finish !")
