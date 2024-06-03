#!/usr/bin/env python3

import requests
import psutil

class IPInfoFetcher:
    def __init__(self):
        self.api_url = 'https://ipinfo.io/'

    def get_ip_info(self, ip=None):
        url = self.api_url
        if ip:
            url += ip
        url += '/json'
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print("Failed to retrieve IP information:", e)
            return None

    def display_ip_info(self, ip_info):
        if ip_info:
            print(f"\nIP Addr:    {ip_info.get('ip')}")
            print(f"Hostname:   {ip_info.get('hostname')}")
            print(f"City:       {ip_info.get('city')}")
            print(f"Region:     {ip_info.get('region')}")
            print(f"Country:    {ip_info.get('country')}")
            print(f"Location:   {ip_info.get('loc')}")
            print(f"ISP:        {ip_info.get('org')}")

def get_network_connections():
    connections = psutil.net_connections(kind='tcp')
    connection_info = []

    for conn in connections:
        laddr = f"{conn.laddr.ip} {conn.laddr.port}"
        raddr = f"{conn.raddr.ip} {conn.raddr.port}" if conn.raddr else ""
        pid = conn.pid if conn.pid else ""
        connection_info.append({
            "proto": "tcp",
            "local_address": laddr,
            "remote_address": raddr,
            "state": conn.status,
            "pid": pid
        })

    return connection_info

def print_connections(connection_info):
    print(f"{'Proto':<5} {'Local Address':<25} {'Remote Address':<25} {'State':<13} {'PID':<5}")
    for info in connection_info:
        print(f"{info['proto']:<5} {info['local_address']:<25} {info['remote_address']:<25} {info['state']:<13} {info['pid']:<5}")

def main():
    fetcher = IPInfoFetcher()
    cons = set()
    
    connections = get_network_connections()
    for c in connections:
        if "127.0.0.1" not in c["local_address"] and "127.0.0.1" not in c["remote_address"] \
            and "10.42.1" not in c["remote_address"] \
            and "192.168." not in c["remote_address"]:
            cons.add(c['remote_address'].split(' ')[0])

    print_connections(connections)

    for addr in cons:
        if addr != '' and addr is not None:
            ip_info = fetcher.get_ip_info(addr)
            fetcher.display_ip_info(ip_info)

if __name__ == "__main__":
    main()
