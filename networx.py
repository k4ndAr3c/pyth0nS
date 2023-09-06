#!/usr/bin/env python3
import time, psutil, os, curses
t = 1

def check(stdscr):
    stdscr.nodelay(True)  # do not wait for input when calling getch
    c = stdscr.getch()
    if c != -1:
        return chr(c)

def main():
    global t, total1, total2
    total1 = total2 = 0
    old_value1 = 0    
    old_value2 = 0    
    c = 0
    while True:
        #if c > 28:
        #    os.system('clear')
        #    c = 0
        mc = curses.wrapper(check)
        if mc == "q":
            exit()
        new_value1 = psutil.net_io_counters().bytes_sent
        new_value2 = psutil.net_io_counters().bytes_recv
        if old_value1 and old_value2:
            send_stat(new_value1 - old_value1, new_value2 - old_value2)
            total1 += (new_value1 - old_value1)
            total2 += (new_value2 - old_value2)
        old_value1 = new_value1
        old_value2 = new_value2
        time.sleep(1)
        c += 1
        t += 1

def convert_to_gbit(value):
    return value//1024.//1024.//1024.*8
#def send_stat(value):
#    print("%0.3f" % convert_to_gbit(value))
def send_stat(value, v):
    global t, total1, total2
    print('<Recv: \033[31m{}\033[0m Kb/s><Sent: \033[32m{}\033[0m Kb/s>\t\t\t\t\t\t(\033[31m{}\033[0m, \033[32m{}\033[0m)'.format(v//1024, value//1024, total2//1024//t, total1//1024//t))
main()
