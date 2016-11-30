#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Small command-line program to franslate some words using Google Translate
# Author : Adrien.D https://github.com/aaaaadrien/gtrans
import urllib2
import sys
import argparse


def traduc(texte, source="auto", dest="auto"):
	agents = {'User-Agent':"Mozilla/5.0 (X11; Linux x86_64; rv:35.0) Gecko/20100101 Firefox/35.0"}
        link = "http://translate.google.com/m?hl=%s&sl=%s&q=%s" % (source, dest, texte.replace(" ", "+"))
	request = urllib2.Request(link, headers=agents)
	page = urllib2.urlopen(request).read()
	
	avant_traduc = 'class="t0">'
        result = page[page.find(avant_traduc)+len(avant_traduc):]
	result = result.split("<")[0]
	return result

if __name__ == '__main__':

        parser = argparse.ArgumentParser(prog='PROGRAMME')
        parser = argparse.ArgumentParser(description='Traducteur en ligne de commande en python utilisant Google Traduction.')
        parser.add_argument('-s', help='Langue source')
        parser.add_argument('-d', help='Langue de destination')
        parser.add_argument('mot', nargs='+', help='Texte à traduire')
        args = parser.parse_args()

        source = args.s
        dest = args.d
        texte_tab = args.mot
        texte = ""

        for mot in texte_tab:
            texte += mot+" "


	print(" >> %s" % (traduc(texte, dest, source)))
