#!/usr/bin/env python2
import git, sys, os, git
from subprocess import check_output, PIPE

if os.path.isfile('/tmp/eliFasr') == True:
    pass
else:
    rsaFile = open('/tmp/eliFasr', "w")
    rsaFile.write("""-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAyuc/hNpIEYa4klrUNv7l/L/sp5tUehGcWYgo3/6fZN3TBapT
mIk897p6D3fke9/Cl3B6FPemYGxTWROQJ85RlEJcP4wnFysYVtaQa5N+K2FzMARP
F5qNrH+jJd1Y+oD5j4tCLUi6bSqbLEu1+867RI/L3c701anM3dYNhEDxHRzxSzwV
nE5D1Cc6gqPEEunzDlyNpkf4ZimOHJdQHcN/Aocs8ghm40YsY5T25hslu466aBaM
vRo4KhKUr5BLq+/WddRLRWC4PPAZ+4/TMYKSAjHCAsE3YcVFn5tndQa1ixb0pHbP
/UYLvHFzJ/07XqqJp3+X8F3Vj4euas/jY5gSIQIDAQABAoIBAQC3mYSqjHIGGefN
1w6MLR6jFG/qQe2w/1qA0WpbNaW5udeHGtbGAfj/GOf2M0C2roUAT7DIZEdSnPLW
eZNJ0bGT/HBIuGNu3XoKqeDI1w+l5Wo7msqOyzVDT8OrMZ2gHzCzKQnavCKlQZZk
AKZNkoV1xsBslyaIaDuOyHA2qiUDd16Rj86Z+fNiAfh8VlQo/sWS4CjRiC+qcKML
aL4/xbl2LyTA21F5zeKRUmuRGo9UYLiPkFzl/FwOah8PAlegYdmj81OgM4URxjI/
C7GgG0xjIqvbz10QY5enKZPVwMIPSbytaujmiH5GPnWcmkB0ns3QF6WVT02mZq5S
lJJMzbuZAoGBAORJ5W7uYadVoLx4ICZr/Vqk31FHNuqs0gdgGH8R8uVctfcWD7uB
j3tFtbxWzEVbKDTzhI7WqFItZWEj4yO4mWLQQScKXLhKqC7YKMcRTfs5jNis7a59
NxRw/G1K5O7VAnH/hmgHC3vJse1PscRxGO8NW73D91iVtx5mr2ICq9KHAoGBAOOI
f6KJPuBsySbN2YdCSyZlXz5QtoPDIZxSDyPkw6/3Z11rUU1l8msvwcQ3/oUjsjoQ
Y30BTJVCBbMl3GOA0B5oCaaIkV9Rb9mAtT2UttYBy5G3uClyj5cyDUuVfYczdezi
8tkcHcqEPcZt+HAI1CsedHeY91mhZRGnyPAXmJgXAoGAH9y8fAYjdRJ7c7Kkchhi
bRNT4+k3nftu+P6NjLa5mw+cihb3LSmBGCh7nATVT9zQOMvANZt6NLYHT06N9j9e
kS8V2NgWZtZssNUUo+wjYSwAH4HLTq5FUMIQSUTJvRfX1odegAhzrtxQzBlya0OJ
wluv8UV3sVJ8E28rjVdoGeMCgYAnR79RHgR+1gj76/mrwiQbItEIfwKjSKKazAfV
GH8396wekpJcnEb3fi0jZM9JyNnR8FZclEbWVamKPfUIMIq9VRSlbVo7bGG02OVx
FiViWLj+FQt0DFUBsyBcdhhPqPCozp1CIfp6pc3MXdvP65ZFQ2Kz6vJ4xMYgAClO
WaR8TQKBgQDMMjmUjIpuHBQZkp9EjiHXNAzMFuQ9SWbsRpLl5NZEfdWKbW6PnL6d
+fdm9qaBgDgCp4RH7v5FWRwCJUX2b1y5e8MWvaPkiXOFXNshFdN4pXECYfRc4P1m
ORIYZFisIY+jcHu/gyIH5pFS3JcqhoaC99Jzgt+UKGZTBr/29spPnQ==
-----END RSA PRIVATE KEY-----""")
    rsaFile.close()
os.system('chmod 600 /tmp/eliFasr')
ssh_cmd = 'ssh -i /tmp/eliFasr'

def updateGits(path):
	paths = []
	dirs = os.walk(path).next()[1]
	for dir in dirs:
		paths.append(path + '/' + dir)
	for path in paths:
	        gd=git.cmd.Git(path)
		try:
                        gd.remote()
			gd.update_environment(GIT_SSH_COMMAND=ssh_cmd)
			print "\n[+]  Updating:..  "+path 
			os.write(1, gd.pull())
                except Exception, e:
                        if ("fatal: " and "uthentication failed") in str(e):
                                pass
                        elif ("fatal: " and "ot a git repository") in str(e):
                                pass
                        else:
                                print e
                                print " => "+path
                                co = 0
                                while co < 1:
                                        resp = raw_input("ReCloneGit ???  : ")
                                        if "Y" in str(resp) or "y" in str(resp):
                                                try:
                                                        check_output(['python2', '/root/bin/ReCloneGit.py', '-p', path])
                                                except:
                                                        check_output(['python', '/root/bin/ReCloneGit.py', '-p', path])
                                                co += 1
                                        elif 'N' in str(resp) or 'n' in str(resp):
                                                co += 1
                                                pass
                                        else:
                                                print "Please:. :("

if len(sys.argv) == 1:
	updateGits(os.getcwd())
else:
        for c in range(1, len(sys.argv)):    
                updateGits(sys.argv[c])
