# Hello, this script is written in Python - http://www.python.org
# Script written by Sebastien SAUVAGE <sebsauvage at sebsauvage dot net> - http://sebsauvage.net
# This script takes whatever you throw at stdin and outputs email addresses.
# eg. python email_extractor.py < PythonFAQ.html
# This script can be used for whatever you want, EXCEPT SPAMMING !
import sys,re
print '\n'.join(re.findall('([\w\.\-]+@[\w\.\-]+)',sys.stdin.read()))
