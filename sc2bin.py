#!/usr/bin/env python
import sys, os
from subprocess import Popen, PIPE
from time import sleep
sc=sys.argv[1]
f=open('/tmp/ShCode{}.c'.format(len(sc)), 'w')
f.write('''const char code[] = "%s";
int main(int argc, char **argv){
	int (*exeshell)();
	exeshell = (int (*)()) code;
	(int)(*exeshell)();
}''' % sc)
f.close()
os.popen('gcc /tmp/ShCode{0}.c -o /tmp/ShCode{0}'.format(len(sc))).read()
print("Bin file at: "+'/tmp/ShCode{}'.format(len(sc)))
#sleep(.3)
#p=Popen(['/tmp/ShCode%s' % len(sc)], stdout=PIPE, shell=True)
#p.communicate()
#sleep(.3)
#os.popen('/tmp/ShCode{}'.format(len(sc))).read()
