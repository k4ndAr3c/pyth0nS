#!/usr/bin/python2
#coding: utf-8
import os, re, sys
from argparse import ArgumentParser

WARNING = '\033[93m'
ENDC = '\033[0m'
OKBLUE = '\033[94m'
BOLD = '\033[1m'

#nbPages = "1"
#region = "16"
#departement = "12"

js_file = "/tmp/leBonCoin.js"
res_file = "/tmp/lbc_results"

parser = ArgumentParser(prog=sys.argv[0])
parser.add_argument('-d', "--departement", type=str, help='Département désiré en chiffre', default="12")
parser.add_argument('-r', "--region", type=str, help='Région désirée en chiffre', default="16")
parser.add_argument('-p', "--prixmax", type=str, help='Prix max désiré', default="300")
parser.add_argument('-n', "--nbpage",  type=str, help='Page à visiter', default="1")
parser.add_argument('-q', "--query",  type=str, help='Mot de recherche', default="")
parser.add_argument('-t', "--type",  type=str, help='Type de recherche (ventes_immobilieres, *locations*, ...)', default="locations")
args = parser.parse_args()

def main():
    with open(js_file, 'w') as f:
        f.write('''const leboncoin = require("leboncoin-api");
var search = new leboncoin.Search()
    .setPage("'''+args.nbpage+'''")
    .setQuery("'''+args.query+'''")
    .setFilter(leboncoin.FILTERS.PARTICULIER)
    .setCategory("'''+args.type+'''")
    .setRegion("'''+args.region+'''")
    .setDepartment("'''+args.departement+'''")
    .addSearchExtra("price", {min: 0, max: '''+args.prixmax+'''}) // will add a range of price
    .addSearchExtra("furnished", ["1", "Non meublé"]); // will add enums for Meublé and Non meublé
 
search.run().then(function (data) {
    console.log(data.page); // the current page
    console.log(data.pages); // the number of pages
    console.log(data.nbResult); // the number of results for this search
    //console.log(data.results); // the array of results
    for (i=0 ; i<=data.results.length ; i++) {
        data.results[i].getDetails().then(function (details) {
      	    console.log(details); // the item 0 with more data such as description, all images, author, ...
            console.log('###########################################################');
        }, function (err) {
      	    console.error(err);
    })};
}, function (err) {
    console.error(err);
});''')
    
    #os.system('nodejs {} > {}'.format(js_file, res_file))

def parse(f1le):
    with open(f1le, 'r') as f:
        temp = f.readlines()
        cur_page, total_page, num_results = temp[0].strip(), temp[1].strip(), temp[2].strip()
        print('\n[+] Current page: {}\n    Total pages: {}\n    Nb of results: {}'.format(cur_page, total_page, num_results))
    annonces = {}
    with open(f1le, 'r') as f:
        co = 0
        page = f.read().split('###########################################################\n')
        for a in page:
            annonces[co] = {}
            try:
                annonces[co]['titre'] = re.findall(".*?title: '(.*.)',\n.*?", a)[0]
            except Exception as e:
                annonces[co]['titre'] = 'nil'
            try:
                annonces[co]['des'] = re.findall(".*?description: '(.*.)',\n.*?", a)[0].replace('\\n', ' ')
            except Exception as e:
                annonces[co]['des'] = 'nil'
            try:
                annonces[co]['lieu'] = re.findall(".*?city_label: '(.*.)',\n.*?", a)[0]
            except Exception as e:
                annonces[co]['lieu'] = 'nil'
            try:
                annonces[co]['date'] = re.findall(".*?date: (.*.),\n.*?", a)[0]#.replace('GMT+0200 (CEST)', ''))
            except Exception as e:
                annonces[co]['date'] = 'nil'
            try:
                annonces[co]['url'] = re.findall(".*?link: '(.*.)',\n.*?", a)[0]
            except Exception as e:
                annonces[co]['url'] = "nil"
            try:
                annonces[co]['prix'] = re.findall(".*?price: (.*.),\n.*?", a)[0]
            except Exception as e:
                annonces[co]['prix'] = "nil"
            try:
                annonces[co]['square'] = re.findall(".*?square: '(.*.)',\n.*?", a)[0]
            except Exception as e:
                annonces[co]['square'] = "nil"
            try:
                print('\n######################################################\n')
                for v in annonces[co]:
                    if v == 'prix':
                        print(OKBLUE+'\t'+annonces[co][v]+"€, "+annonces[co]['square']+"m²"+ENDC)
                    elif v == 'square':
                        pass
                    elif v == 'lieu' or v == 'titre':
                        print(WARNING+"\t"+annonces[co][v]+ENDC)
                    elif v == 'des':
                        print(BOLD+annonces[co][v]+ENDC)
                    elif v == 'date':
                        print('\t'+annonces[co][v])
                    else:
                        print annonces[co][v]
            except Exception as e:
                print e
            co += 1

main()
parse(res_file)
