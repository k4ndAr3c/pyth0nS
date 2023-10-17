#!/usr/bin/env python3

from itertools import combinations, product
from bs4 import BeautifulSoup
from time import sleep
import argparse
import requests
from random import choice
from colorama import init as colorama_init, Fore, Style

CATEGORIES = ['Steganography', 'Cryptanalysis', 'Forensic', 'Programming', 'Cracking', 'Realist', 'Web-Server', 'App-System', 'App-Script', 'Web-Client', 'Network']
HEAD = {'User-Agent':'Firefox 170'}
COLORS = [Fore.RED, Fore.GREEN, Fore.YELLOW, Fore.BLUE, Fore.MAGENTA, Fore.CYAN, Fore.WHITE]

def get_page(pseudo):
    r = requests.get(f"https://www.root-me.org/{pseudo}?inc=score&lang=en", headers=HEAD)
    if r.status_code == 200:
        return BeautifulSoup(r.text, 'html.parser')
    else:
        print(f"{Fore.RED}[!]{Style.RESET_ALL} Invalid username")
        exit()

def get_challenges(page):
	links = page.find_all("a", class_="rouge")
	todos = []
	for link in links:
		category = link.get("href").split("/")[2].lower()
		name = link.text.strip().replace("x\xa0", "")
		points = int(link.get("title").split()[0])
		todos.append( (category, name, points) )
	return todos

def get_points(page):
	points = int(page.find_all("h3")[5].text)
	return points

def filter_by_categories(challenges, add_categories, remove_categories):
    global CATEGORIES
    if add_categories == None and remove_categories == None:
        return challenges
    
    c = []
    if add_categories == None:
        c = [e for e in CATEGORIES if e not in remove_categories]
    elif remove_categories == None:
        c = add_categories

    return [challenge for challenge in challenges if challenge[0] in c]
    
def parse_categories(raw):
	# add mechanisme to recognise the intended category and fix it
    if raw == None:
        return None
    return list(map(lambda x: x.strip().lower(), raw.split(",")))

def compute_combinations(challenges, points, goal, depth):
    valid_combinations = []
    find_combinations(challenges, points, goal, depth, [], valid_combinations, set())
    valid_combinations.sort(key=lambda x: sum(challenge[2] for challenge in x))
    return valid_combinations

def find_combinations(challenges, points, goal, depth, current_combination, valid_combinations, used_challenges):
    if points == goal:
        sorted_combination = sorted(current_combination, key=lambda x: x[2])
        if sorted_combination not in valid_combinations:
            valid_combinations.append(sorted_combination)
    elif points < goal and depth > 0:
        for challenge in challenges:
            category, name, point_value = challenge
            if challenge not in used_challenges:
                new_points = points + point_value
                new_depth = depth - 1
                new_combination = current_combination + [challenge]
                new_used_challenges = used_challenges.copy()
                new_used_challenges.add(challenge)
                find_combinations(challenges, new_points, goal, new_depth, new_combination, valid_combinations, new_used_challenges)
                find_combinations(challenges, points, goal, new_depth, current_combination, valid_combinations, used_challenges)

def display_welcome():
    pass

def display_results(username, points, goal, combinations):
    print(f"{Fore.BLUE}[*]{Style.RESET_ALL} {username} : {points}")
    print(f"{Fore.BLUE}[*]{Style.RESET_ALL} Goal : {goal}")
    print()
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} Found {Fore.YELLOW}{len(combinations)}{Style.RESET_ALL} combinations")
    print()
    print(f"{Fore.CYAN}=========================={Style.RESET_ALL}")
    print()
    for i, combination in enumerate(combinations):
        if i >= 250: 
            print()
            exit(0)
        print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {i+1}")
        for challenge in combination:
            c, n, p = challenge
            print(f"\t{Fore.BLUE}[*]{Style.RESET_ALL} {p}\t: [{c}] {n}")
        print()

def parse_args():
    parser = argparse.ArgumentParser(description='Offers rootme challenges combinations to reach a goal')
    parser.add_argument('username', type=str, help='The rootme username. You can find it in your profile\'s URL')
    parser.add_argument("-g", '--goal', type=int, help='The goal to reach')
    parser.add_argument('-d', '--depth', type=int, metavar='', default=3, help='The maximum number of challenges to combine. Default is 3, higher than 4 may take a long time')
    parser.add_argument('-m', '--max', type=int, default=25, help='The maximum number of challenges to print')
    parser.add_argument('-s', '--sec', type=int, default=2, help='The number of seconds to sleep between requests')
    parser.add_argument('-N', '--next', help='Get score of next player', action="store_true")
    parser.add_argument('-L', '--light', help='Just print todos challs sorted by pts', action="store_true")

    category_group = parser.add_mutually_exclusive_group(required=False)
    category_group.add_argument('-a', '--add-categories', type=str, metavar='', default=None, help='The categories to include, separated by commas. Default is all categories')
    category_group.add_argument('-e', '--exclude-categories', type=str, metavar='',default=None, help='The categories to exclude, separated by commas. Default is all categories')
    args = parser.parse_args()
    return args.username, args.goal, args.depth, args.max, args.sec, args.next, args.light, parse_categories(args.add_categories), parse_categories(args.exclude_categories)

def get_validations(cat):
    r = requests.get(f"https://www.root-me.org/en/Challenges/{cat}/", headers=HEAD)
    if r.status_code == 200:
        return BeautifulSoup(r.text, 'html.parser')
    else:
        sleep(11)
        r = requests.get(f"https://www.root-me.org/en/Challenges/{cat}/", headers=HEAD)
        if r.status_code == 200:
            return BeautifulSoup(r.text, 'html.parser')
        else:
            print(f"{Fore.RED}[!]{Style.RESET_ALL} Invalid category ({cat})")
            exit()

def get_val_val(tds):
    res = []
    for _ in tds.find_all('td'):
        links = _.find_all("a", title="Who ?")
        for l in links:
            res.append(int(l.text))
    return res

def get_href(res, cat):
    links = []
    for tds in res.find_all('tr'):
        for _td in tds.find_all('a'):
            if "en/Challenges/{}".format(cat) in _td.get('href') and "?" not in _td.get("href"):
                if _td.text != '\xa0' and _td.text not in links:
                    links.append(_td.text)
    return links

def get_next(pseudo):
    r = requests.get(f"https://www.root-me.org/{pseudo}?inc=info&lang=en", headers=HEAD)
    if r.status_code == 200:
        res = BeautifulSoup(r.text, 'html.parser')
        for _ in res.find_all("td"):
            __ = res.find_all("a")
            for _a in range(len(__)):
                if pseudo in __[_a]:
                    n3xt = (__[_a-1].get('href').split('?')[0], int(__[_a-1].text))
                    return n3xt

    else:
        print(f"{Fore.RED}[!]{Style.RESET_ALL} Invalid username")
        exit()

def main():
    colorama_init()
    #display_welcome()
    username, goal, depth, MAX, SEC, N, L, add_categories, exclude_categories = parse_args()
    page = get_page(username)
    challenges = get_challenges(page)
    points = get_points(page)
    challenges = filter_by_categories(challenges, add_categories, exclude_categories)

    if N:
        n3xt = get_next(username)
        print(f"Next player: {n3xt[0]} has {n3xt[1]}")
        goal = n3xt[1]

    if goal:
        cmb = compute_combinations(challenges, points, goal, depth)
        display_results(username, points, goal, cmb)
        exit(0)

    sorted_challs = sorted(challenges, key=lambda x: x[2])

    if L:
        i = 0
        print()
        for sc in sorted_challs:
            if i > MAX: 
                print()
                exit(0)
            print(f"{Fore.GREEN}[+]{Fore.YELLOW} {sc[0]:<15}{Fore.BLUE} {sc[1]}{Fore.RED} {sc[2]}{Style.RESET_ALL}")
            i += 1
        print()
        exit(0)

    #print(sorted_challs)
    val_dic = {}
    all_cat = []
    all_cat.append([c for c, n, p in sorted_challs])
    all_cat = set(all_cat[0])
    links_name = []
    for _ in CATEGORIES:
        if _.lower() in all_cat:
            print(_, end=" ", flush=True)
            res = get_validations(_)
            validations = get_val_val(res)
            #print(validations)
            links = get_href(res, _)
            #print(links)
            assert len(validations) == len(links)
            sleep(SEC)
        for i in range(len(links)):
            val_dic[links[i]] = validations[i]
        #print(val_dic)
    
    todos = []
    print("\n")
    for todo in sorted_challs:
        if todo[1] in val_dic.keys():
            todos.append( (todo, val_dic[todo[1]]) )
    
    i = 0
    todos = reversed(sorted(todos, key=lambda x: x[1]))
    with open('/tmp/todo_challs.txt', 'w') as f:
        r1 = choice(COLORS)
        r2 = choice(COLORS)
        r3 = choice(COLORS)
        r4 = choice(COLORS)
        for t in todos:
            if i > MAX: 
                print()
                exit(0)
            s = f"{r1}[+]{Style.RESET_ALL} [{t[0][0]:<15}> {r2} {t[0][1]:<40}  {r3}{t[0][2]} pts{Style.RESET_ALL} => {r4}{t[1]} vals{Style.RESET_ALL}"
            print(s)
            f.write(s+"\n")
            i += 1
    print()

if __name__ == "__main__":
	main()

