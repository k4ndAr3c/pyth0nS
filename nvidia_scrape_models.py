#!/usr/bin/env python3
"""
NVIDIA Build Models Scraper - Improved

Scrapes model listings from build.nvidia.com with better selectors
and popularity data extraction from RSC payloads.

Requires:
    pip install selenium webdriver-manager

Usage:
    python nvidia_scrape_models.py [-s recent|popular|name] [-l N]
"""

import os
import sys
import argparse
import json
import time
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.firefox import GeckoDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


def setup_driver():
    """Setup Firefox WebDriver with options."""
    firefox_options = Options()
    firefox_options.add_argument("--headless")
    firefox_options.add_argument("--no-sandbox")
    firefox_options.add_argument("--disable-dev-shm-usage")
    firefox_options.set_preference("general.useragent.override", 
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0")
    
    service = Service(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=firefox_options)
    return driver


def parse_relative_date(date_str: str) -> str:
    """Convert relative dates like 'Today', '14d', '1m' to YYYY-MM-DD."""
    now = datetime.now()
    date_str = date_str.lower().strip()
    
    if date_str == "today":
        return now.strftime("%Y-%m-%d")
    if date_str == "yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    
    match = re.match(r'(\d+)([dwmy])', date_str)
    if match:
        val, unit = match.groups()
        val = int(val)
        if unit == 'd':
            return (now - timedelta(days=val)).strftime("%Y-%m-%d")
        if unit == 'w':
            return (now - timedelta(weeks=val)).strftime("%Y-%m-%d")
        if unit == 'm':
            return (now - timedelta(days=val*30)).strftime("%Y-%m-%d")
        if unit == 'y':
            return (now - timedelta(days=val*365)).strftime("%Y-%m-%d")
            
    return date_str


def extract_popularity_from_rsc(driver) -> List[str]:
    """
    Cleverly extract popularity data from Next.js RSC payloads.
    Returns a list of apiInvocations in the order they appear.
    """
    all_invocations = []
    try:
        scripts = driver.find_elements(By.TAG_NAME, "script")
        for s in scripts:
            try:
                content = s.get_attribute("innerHTML")
                if content and "apiInvocations" in content:
                    # Find all counts. They look like \"apiInvocations\":\"12345\"
                    matches = re.findall(r'\\?"apiInvocations\\?":\\?"(\d+)\\?"', content)
                    all_invocations.extend(matches)
            except:
                continue
    except Exception as e:
        pass
    return all_invocations


def scrape_nvidia_models(sort_by: str = "recent", limit: int = 50) -> List[Dict]:
    """
    Scrape models from build.nvidia.com.
    """
    if not SELENIUM_AVAILABLE:
        print("Error: selenium and webdriver-manager are required.")
        sys.exit(1)
    
    sort_params = {
        "recent": "dateCreated:DESC",
        "popular": "weightPopular:DESC",
        "name": "name:ASC",
    }
    
    order_by = sort_params.get(sort_by, "dateCreated:DESC")
    url = f"https://build.nvidia.com/models?filters=nimType%3Anim_type_preview&orderBy={order_by}"
    
    print(f"Scraping {url}...")
    
    driver = setup_driver()
    models = []
    
    try:
        driver.get(url)
        
        # Wait for model cards to appear
        print("Waiting for models to load...")
        card_found = False
        for wait_time in [15, 10, 5]:
            try:
                WebDriverWait(driver, wait_time).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='nv-card-root']"))
                )
                card_found = True
                break
            except:
                print(f"Still waiting ({wait_time}s)...")
                # Try to scroll a bit to trigger loading
                driver.execute_script("window.scrollBy(0, 500);")
                time.sleep(2)
        
        if not card_found:
            print("Timed out waiting for cards. Checking if page content is present...")
            # Fallback: check if any links exist
            if len(driver.find_elements(By.TAG_NAME, "a")) > 20:
                print("Found many links, attempting to parse anyway.")
            else:
                print(f"Error: Page didn't load correctly. Title: {driver.title}")
                return []

        # Scroll to load more if needed
        if limit > 20:
            last_height = driver.execute_script("return document.body.scrollHeight")
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height: break
                last_height = new_height

        # Extract stats from RSC as a clever bonus
        invocations = extract_popularity_from_rsc(driver)
        if invocations:
            print(f"Extracted {len(invocations)} usage stats from RSC payloads.")

        # Parse cards
        cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='nv-card-root']")
        print(f"Found {len(cards)} model cards.")
        
        seen_ids = set()
        for i, card in enumerate(cards[:limit]):
            try:
                # Extract text lines
                text_lines = [l.strip() for l in card.text.split('\n') if l.strip()]
                if not text_lines: continue
                
                model = {}
                
                # Use links to get the real ID and owner
                links = card.find_elements(By.TAG_NAME, "a")
                model_id = "unknown"
                owner = "Unknown"
                
                for link in links:
                    href = link.get_attribute("href")
                    if href:
                        # Path structure is https://build.nvidia.com/owner/name
                        parts = href.rstrip('/').split('/')
                        if len(parts) >= 5 and parts[3] not in ['models', 'explore', 'settings']:
                            owner = parts[3]
                            model_id = parts[4]
                            break
                
                if model_id == "unknown" and len(text_lines) > 2:
                    # Fallback to text lines: Owner is usually line 0, ID is line 2
                    owner = text_lines[0]
                    model_id = text_lines[2]

                # Full name for display
                full_name = f"{owner}/{model_id}"
                if full_name in seen_ids: continue
                seen_ids.add(full_name)
                
                model['name'] = full_name
                model['owner'] = owner
                model['id'] = model_id
                
                # Date is usually the last line
                model['created'] = parse_relative_date(text_lines[-1])
                
                # Popularity from RSC if available, matched by index
                model['popularity'] = invocations[i] if i < len(invocations) else "N/A"
                
                models.append(model)
                
            except Exception as e:
                continue
        
        return models
        
    except Exception as e:
        print(f"Error during scraping: {e}")
        return []
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Scrape NVIDIA models from build.nvidia.com")
    parser.add_argument("-s", "--sort", choices=["recent", "popular", "name"], default="popular")
    parser.add_argument("-l", "--limit", type=int, default=50)
    args = parser.parse_args()
    
    print("Starting NVIDIA models scraper...")
    models = scrape_nvidia_models(sort_by=args.sort, limit=args.limit)
    
    if not models:
        print("No models found.")
        sys.exit(1)
    
    print("\n" + "=" * 90)
    print(f"{'MODEL':<50} {'OWNER':<15} {'DATE':<12} {'INVOCATIONS':<15}")
    print("=" * 90)
    
    for model in models:
        name = str(model.get('name', 'N/A'))[:49]
        owner = str(model.get('owner', 'N/A'))[:14]
        date = str(model.get('created', 'N/A'))[:11]
        pop = str(model.get('popularity', 'N/A'))[:14]
        print(f"{name:<50} {owner:<15} {date:<12} {pop:<15}")
    
    print(f"\nTotal: {len(models)} models")


if __name__ == "__main__":
    main()
