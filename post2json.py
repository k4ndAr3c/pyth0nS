#!/usr/bin/env python3
from sys import argv

params = argv[1]
params = params.replace('=', '":"').replace('&', '","')
print(f'{{"{params}"}}')
