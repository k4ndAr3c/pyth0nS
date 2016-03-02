# -*- coding:Utf-8 -*-
#!/usr/bin/env python2.7
#auteur:k4ndAr3c

import fnmatch, shutil
import os, random, sys
 
rootPath = str(sys.argv[1])
pattern = '*.mp3'
i=1   
l=[]

for root, dirs, files in os.walk(rootPath):
	for filename in fnmatch.filter(files, pattern):
		l.append(os.path.join(root, filename))

lo = len(l)
		
while i<int(sys.argv[3]):														
	b = random.randint(1, lo)	
	shutil.copy2(l[b],sys.argv[2])
        print "%i  Copying %s" % (i, l[b])
	i=i+1	
	

