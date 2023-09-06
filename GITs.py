#!/usr/bin/env python3
#encoding: utf-8
import git, sys, os, re

if os.path.isfile('/tmp/eliFasr') == True:
    pass
else:
    rsaFile = open('/tmp/eliFasr', "w")
    rsaFile.write("""-----BEGIN OPENSSH PRIVATE KEY-----
-----END OPENSSH PRIVATE KEY-----
""")
    rsaFile.close()
os.system('chmod 600 /tmp/eliFasr')
ssh_cmd = 'ssh -i /tmp/eliFasr'
r1 = ".*?url = (.*.)\n.*?"

def recloneGit(path):
	url = re.findall(r1, open(path+".SVG/.git/config").read())[0]
	if "No" in url:
		print(" [-] This is not a git repo")
	elif "Aucun" in url:
		print(" [-] Ce n'est pas un dépot git")
	else:
		print("[+] Cloning {} => {}".format(url, path))
		os.system("git clone "+str(url)+" "+path)

def rm_svg(path2svg):
    while True:
        a = input(" ``''--__:: Do you want to rm svg ? ::--''``" ).lower()
        if a == 'y':
            os.system("rm -Rfv "+path2svg+".SVG")
            break
        elif a == "n":
            #os.system("mv -v "+path2svg+".SVG "+path2svg)
            break

def updateGits(path):
	paths = []
	for x, y, z in os.walk(path):
		dirs = y
		break
	for d in dirs:
		paths.append(path + '/' + d)
	for path in paths:
		gd=git.cmd.Git(path)
		try:
			gd.remote()
			gd.update_environment(GIT_SSH_COMMAND=ssh_cmd)
			print("\n[+]  Updating:..  "+path)
	            #res = gd.pull()
	            #if "Username for 'https://github.com':" in res:
	            #        os.write(3, "\n")
	            #        os.write(3, "\n")
				#os.write(1, res)
			os.write(1, bytes(gd.pull(), 'utf-8'))
		except Exception as e:
			if ("fatal: " and "uthentication failed") in str(e):
				pass
			elif ("fatal: " and "ot a git repository") in str(e):
				pass
			elif ("fatal: " and "not found") in str(e):
				print("\033[93m[-] Not found:.  {}\033[0m".format(path))
			elif ("fatal: unable to update url base from redirection") in str(e):
				print("\033[93m[-] Invalid redirection:.  {}\033[0m".format(path))
			elif ("SSL: certificate" and "does not match target host name") in str(e):
				print("\033[93m[-] SSL error:.  {}\033[0m".format(path))
			elif ("fatal: " and "not valid: is this a git repository?") in str(e):
				print("\033[93m[-] Is this a git repository? :.  {}\033[0m".format(path))
			elif ("fatal: " and "Could not resolve") in str(e):
				print("\033[93m[-] Could not resolve host:.  {}\033[0m".format(path))
			elif ("fatal: " and "esolving timed out") in str(e):
				print("\033[93m[-] Could not resolve host:.  {}\033[0m".format(path))
			elif ("fatal: " and "Couldn't resolve") in str(e):
				print("\033[93m[-] Could not resolve host:.  {}\033[0m".format(path))
			elif ("fatal: " and "nable to look up") in str(e):
				print("\033[93m[-] Unable to look up:.  {}\033[0m".format(path))
			elif ("fatal: " and "this operation must be run in a work tree") in str(e):
				print("\033[93m[-] This operation must be run in a work tree:.  {}\033[0m".format(path))
			elif ("Failed to connect" and "Connection refused") in str(e):
				print("\033[93m[-] Connection refused:.  {}\033[0m".format(path))
			else:
				print(e)
				print(" => "+path)
				co = 0
				while co < 1:
					resp = input("ReCloneGit ???  : ")
					if "y" in str(resp).lower():
						os.system("mv -v {0} {0}.SVG".format(path))
						recloneGit(path)
						rm_svg(path)
						co += 1
					elif 'n' in str(resp).lower():
						co += 1
						pass
					else:
						print("Please:. :(")

if len(sys.argv) == 1:
	updateGits(os.getcwd())
else:
	for c in range(1, len(sys.argv)):    
		updateGits(sys.argv[c])
