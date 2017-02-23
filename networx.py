#!/usr/bin/env python
import time, psutil

def main():
    old_value1 = 0    
    old_value2 = 0    
    while True:
        new_value1 = psutil.net_io_counters().bytes_sent
        new_value2 = psutil.net_io_counters().bytes_recv
        if old_value1 and old_value2:
            send_stat(new_value1 - old_value1, new_value2 - old_value2)
        old_value1 = new_value1
        old_value2 = new_value2
        time.sleep(1)

def convert_to_gbit(value):
    return value/1024./1024./1024.*8

#def send_stat(value):
#    print("%0.3f" % convert_to_gbit(value))
def send_stat(value, v):
    print('<Recv: \033[31m{}\033[0m Kb/s><Sent: \033[32m{}\033[0m Kb/s>'.format(v/1024, value/1024))

main()
