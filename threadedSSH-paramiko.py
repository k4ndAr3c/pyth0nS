#!/usr/bin/python2

import Queue
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
			print "\t.:| %s |:." % counter
			try:
				ssh.connect(counter)
			except:
				print '[-] Failed to connect with %s\n' % counter
			else:
				stdin, stdout, stderr = ssh.exec_command(CMD)
				for line in stdout.readlines():
					print line.strip()
				print "\n"
			ssh.close()
			self.queue.task_done()


l = subprocess.check_output(['arp-scan', '-l']).split('\n')
CMD = str(sys.argv[1])
hosts = l[2:-4]
ips = ['10.42.2.1']
macs = []

for a in hosts:
	ip, mac, mark = a.split('\t')
        if ip != "10.42.1.100":
	    ips.append(ip)
	    macs.append(mac)
	
queue = Queue.Queue()

for i in range(len(ips)):
	worker = WorkerThreads(queue)
	worker.setDaemon(True)
	worker.start()
	#print "Worker %i created" % i

for j in ips:
	queue.put(j)

queue.join()

print "Finish !"
