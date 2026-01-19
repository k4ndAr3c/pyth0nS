#!/usr/bin/env python3
"""
Script to scrape search results from RapidDNS.
Usage: python3 scrape_rapiddns.py <domain>
"""

import sys
import requests
from bs4 import BeautifulSoup

def scrape_rapiddns(domain):
    """
    Scrape search results for a given domain on RapidDNS.
    
    Args:
        domain (str): The domain to search for
        
    Returns:
        list: A list of dictionaries containing table row data
    """
    url = f"https://rapiddns.io/s/{domain}#result"
    
    try:
        # Send a GET request to the URL
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception if the request fails
        
        # Parse the HTML content with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the tbody
        tbody = soup.find('tbody')
        
        if not tbody:
            print("No tbody found on the page.")
            return []
        
        # Initialize a list to store data
        data = []
        
        # Iterate through each row (tr) in the tbody
        for tr in tbody.find_all('tr'):
            # Find all cells (td) in the row
            tds = tr.find_all('td')
            
            # Extract text from each cell
            row_data = [td.get_text(strip=True) for td in tds]
            
            # Add row data to the list
            data.append(row_data)
        
        return data
        
    except requests.exceptions.RequestException as e:
        print(f"Error during HTTP request: {e}")
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scrape_rapiddns.py <domain>")
        sys.exit(1)
    
    domain = sys.argv[1]
    # print(f"Searching for results for domain: {domain}")
    
    # Scrape the data
    results = scrape_rapiddns(domain)
    
    # Display the results - only column 1 values
    if results:
        print(f"{domain} virtual hosts:")
        # Extract only the first column values
        column1_values = [row[0] for row in results if len(row) > 0]
        
        # Print values in columns (3 values per line)
        for i in range(0, len(column1_values), 3):
            # Get up to 3 values for this line
            line_values = column1_values[i:i+3]
            # Print each value with fixed width for alignment (40 characters)
            print("  ".join(f"{value:<50}" for value in line_values))
    else:
        print("No results found.")

if __name__ == "__main__":
    main()
