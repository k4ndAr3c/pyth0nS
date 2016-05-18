#!/usr/bin/python2
#auteur:k4ndAr3c

import Queue
import time
import threading
import subprocess

class WorkerThreads(threading.Thread):
	
	def __init__(self, queue):
		threading.Thread.__init__(self)
		self.queue = queue

	def run(self):
		while True:
			counter = self.queue.get()
			print "\t.:` %s `:.\n" % counter
			subprocess.call(['ssh', counter, 'uname', '-a'])
			self.queue.task_done()

l = subprocess.check_output(['arp-scan', '-l']).split('\n')
hosts = l[2:-4]
ips = []
macs = []

for a in hosts:
	ip, mac, mark = a.split('\t')
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
