#!/usr/bin/env python3
"""
Re-process existing HTML files with updated parser logic
"""

import os
import json
import pandas as pd
from pathlib import Path
from scraper.steg_parser import STEGParser
from bs4 import BeautifulSoup

def main():
    html_dir = Path("data/raw/html")
    parser = STEGParser()
    
    all_records = []
    
    print(f"📁 Reading HTML files from {html_dir}")
    html_files = list(html_dir.glob("*.html"))
    print(f"Found {len(html_files)} HTML files")
    
    for html_file in html_files:
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract metadata
            # Title comes from page <title> tag, not H1
            page_title = soup.find('title')
            title_text = page_title.get_text(strip=True) if page_title else "N/A"
            # Extract just the announcement part (before | separator)
            if '|' in title_text:
                title_text = title_text.split('|')[0].strip()
            
            # FILTER: Skip non-outage articles
            if "إشعار" not in title_text and "انقطاع" not in title_text:
                continue
            
            # Body is in field-name-body div
            body = soup.find('div', class_='field-name-body')
            body_text = body.get_text(separator='\n', strip=True) if body else ""
            
            # Double-check body also contains outage keywords
            if "انقطاع" not in body_text:
                continue
            
            # Published date - try to extract from title or metadata
            published_at = ""
            date_span = soup.find('span', class_='date-display-single')
            if date_span and date_span.has_attr('content'):
                published_at = date_span.get('content')
            else:
                # Try to extract from title: "- HH:MM DD/MM/YYYY"
                import re
                date_match = re.search(r'(\d{2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})', title_text)
                if date_match:
                    h, m, d, mon, y = date_match.groups()
                    published_at = f"{y}-{mon}-{d} {h}:{m}"
            
            # Parse article
            url = f"https://www.steg.com.tn/fr/news/{html_file.stem}"
            record = parser.parse_article(url, title_text, body_text, published_at)
            all_records.append(record)
            
        except Exception as e:
            print(f"⚠️ Error processing {html_file.name}: {e}")
            continue
    
    print(f"\n✅ Parsed {len(all_records)} records")
    
    # Export to CSV
    csv_path = Path("data/processed/steg_outages.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(all_records)
    df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f"💾 Saved CSV: {csv_path}")
    
    # Export to Excel
    excel_path = Path("data/processed/steg_outages.xlsx")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='STEG_Outages', index=False)
    print(f"💾 Saved Excel: {excel_path}")
    
    # Export to JSON
    json_path = Path("data/processed/steg_outages.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved JSON: {json_path}")
    
    print("\n✅ Done! Check data/processed/")

if __name__ == "__main__":
    main()
