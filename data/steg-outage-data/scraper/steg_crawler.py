"""
STEG Crawler — Main orchestrator for official outage data collection
Entry point: python -m scraper.steg_crawler
"""

import requests
import json
import time
import random
import logging
import ssl
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows

from .steg_parser import STEGParser
from .steg_validator import STEGValidator
from .deduplicator import STEGDeduplicator


class STEGCrawler:
    """Main crawler for STEG outage announcements"""
    
    BASE_URL = "https://www.steg.com.tn"
    NEWS_URL = f"{BASE_URL}/fr/news"
    TARGET_START_DATE = "2026-07-01"
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.parser = STEGParser()
        self.validator = STEGValidator()
        self.deduplicator = STEGDeduplicator()
        
        # Setup logging
        log_path = data_dir / "logs" / "extraction.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_path, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Session setup
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0'
        })
        
        # Disable SSL verification (STEG cert issues)
        self.session.verify = False
        requests.packages.urllib3.disable_warnings()
    
    def run(self):
        """Main execution flow"""
        self.logger.info("="*60)
        self.logger.info("STEG OFFICIAL ELECTRICITY OUTAGE DATA SCRAPER")
        self.logger.info("="*60)
        
        # PHASE 1: Discovery
        article_links = self.discover_articles()
        self.logger.info(f"Discovered {len(article_links)} article links")
        
        # PHASE 2: Download + Parse
        records = self.download_and_parse(article_links)
        self.logger.info(f"Extracted {len(records)} records")
        
        # PHASE 3: Validate
        for record in records:
            status, notes = self.validator.validate(record)
            record["verification_status"] = status
            record["verification_notes"] = notes
            record["id"] = self.validator.generate_id(record)
        
        # PHASE 4: Deduplicate
        unique_records = self.deduplicator.deduplicate(records)
        removed = len(records) - len(unique_records)
        if removed > 0:
            self.logger.info(f"Removed {removed} duplicate(s)")
        
        # PHASE 5: Export
        self.export_results(unique_records)
        
        # PHASE 6: Report
        self.print_final_report(unique_records)
    
    def discover_articles(self) -> List[Dict]:
        """
        PHASE 1: Discover all article links from paginated news listing
        Returns: list of {url, title, published_at}
        """
        self.logger.info("Starting article discovery...")
        
        # Detect max page
        html = self._fetch_with_retry(self.NEWS_URL)
        soup = BeautifulSoup(html, 'lxml')
        max_page = self._detect_max_page(soup)
        self.logger.info(f"Detected max_page = {max_page}")
        
        articles = []
        for page_num in range(0, max_page + 1):
            page_url = self.NEWS_URL if page_num == 0 else f"{self.NEWS_URL}?page={page_num}"
            self.logger.info(f"Scanning page {page_num}...")
            
            html = self._fetch_with_retry(page_url)
            soup = BeautifulSoup(html, 'lxml')
            
            page_articles = self._extract_articles_from_page(soup)
            
            # Check if we've gone too far back in time
            if self._all_articles_too_old(page_articles):
                self.logger.info(f"Page {page_num}: all articles older than {self.TARGET_START_DATE}, stopping")
                break
            
            articles.extend(page_articles)
            self.logger.info(f"Page {page_num}: found {len(page_articles)} articles")
            
            time.sleep(random.uniform(1.0, 2.0))  # Politeness delay
        
        return articles
    
    def _detect_max_page(self, soup: BeautifulSoup) -> int:
        """Find the last page number from pager"""
        pager_last = soup.find('li', class_='pager-last')
        if pager_last:
            link = pager_last.find('a', href=True)
            if link:
                import re
                match = re.search(r'page=(\d+)', link['href'])
                if match:
                    return int(match.group(1))
        return 13  # Fallback
    
    def _extract_articles_from_page(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract article metadata from a listing page"""
        articles = []
        rows = soup.find_all('div', class_=lambda x: x and 'views-row' in x)
        
        for row in rows:
            # Get link
            link = row.find('a', href=lambda x: x and '/fr/news/' in x)
            if not link:
                continue
            
            url = self.BASE_URL + link['href'] if link['href'].startswith('/') else link['href']
            
            # Get title (usually inside the link or nearby h4)
            title = link.get_text(strip=True)
            if not title:
                h4 = row.find('h4')
                title = h4.get_text(strip=True) if h4 else "Unknown"
            
            # FILTER: Only include outage announcements "إشعار بانقطاع الكهرباء"
            if "إشعار" not in title and "انقطاع" not in title:
                continue  # Skip non-outage articles
            
            # Get published_at (look for date pattern DD/MM/YYYY - HH:MM)
            text = row.get_text()
            import re
            pub_match = re.search(r'(\d{2}/\d{2}/\d{4}\s*-\s*\d{2}:\d{2})', text)
            published_at = pub_match.group(1) if pub_match else None
            
            articles.append({
                "url": url,
                "title": title,
                "published_at": published_at
            })
        
        return articles
    
    def _all_articles_too_old(self, articles: List[Dict]) -> bool:
        """Check if all articles are older than target start date"""
        if not articles:
            return True
        
        for article in articles:
            pub = article.get("published_at", "")
            # Quick check: if date contains "2026" and month >= 07, it's recent
            if "2026" in pub:
                import re
                match = re.search(r'(\d{2})/(\d{2})/2026', pub)
                if match:
                    month = int(match.group(2))
                    if month >= 7:  # July or later
                        return False
        
        return True  # All too old
    
    def download_and_parse(self, article_links: List[Dict]) -> List[Dict]:
        """
        PHASE 2: Download each article and parse
        Returns: list of parsed records
        """
        records = []
        total = len(article_links)
        
        for idx, article_meta in enumerate(article_links, 1):
            self.logger.info(f"[{idx}/{total}] Processing: {article_meta['title'][:50]}...")
            
            try:
                # Download
                html = self._fetch_with_retry(article_meta['url'])
                
                # Save raw HTML
                self._save_html(article_meta['url'], html)
                
                # Extract body
                soup = BeautifulSoup(html, 'lxml')
                body_div = soup.find('div', class_='field-name-body')
                body_text = body_div.get_text(separator='\n', strip=True) if body_div else ""
                
                # Check if it's an outage announcement
                if "انقطاع" not in body_text:
                    self.logger.info(f"  Skipped: not an outage announcement")
                    continue
                
                # Parse
                record = self.parser.parse_article(
                    url=article_meta['url'],
                    title=article_meta['title'],
                    body=body_text,
                    published_at=article_meta['published_at'] or ""
                )
                
                records.append(record)
                self.logger.info(f"  Extracted: date={record.get('outage_date')}, region={record.get('region')}")
                
            except Exception as e:
                self.logger.error(f"  Error: {e}")
            
            time.sleep(random.uniform(1.5, 3.0))  # Politeness
        
        return records
    
    def _fetch_with_retry(self, url: str, max_retries: int = 3) -> str:
        """Fetch URL with exponential backoff retry"""
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                if attempt == max_retries:
                    raise
                wait = 2 ** attempt
                self.logger.warning(f"Retry {attempt}/{max_retries} after {wait}s: {e}")
                time.sleep(wait)
    
    def _save_html(self, url: str, html: str):
        """Save raw HTML for reproducibility"""
        # Generate filename from URL
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"{url_hash}.html"
        
        html_dir = self.data_dir / "data" / "raw" / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        
        path = html_dir / filename
        path.write_text(html, encoding='utf-8')
    
    def export_results(self, records: List[Dict]):
        """PHASE 5: Export to JSON, CSV, Excel"""
        self.logger.info("Exporting results...")
        
        # JSON export
        json_path = self.data_dir / "data" / "raw" / "steg_outages_raw.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        self.logger.info(f"Saved JSON: {json_path}")
        
        # CSV export
        df = pd.DataFrame(records)
        csv_path = self.data_dir / "data" / "processed" / "steg_outages.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False, encoding='utf-8')
        self.logger.info(f"Saved CSV: {csv_path}")
        
        # Excel export (4 sheets)
        self._export_excel(records)
    
    def _export_excel(self, records: List[Dict]):
        """Create Excel workbook with 4 sheets"""
        excel_path = self.data_dir / "data" / "processed" / "steg_outages.xlsx"
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # Sheet 1: Main data
            df = pd.DataFrame(records)
            df.to_excel(writer, sheet_name='STEG_Outages', index=False)
            
            # Sheet 2: Summary
            self._create_summary_sheet(writer, records)
            
            # Sheet 3: Extraction Log (placeholder)
            log_df = pd.DataFrame([
                {"url": r["source_url"], "status": "200", "page_type": "outage", "error": None}
                for r in records
            ])
            log_df.to_excel(writer, sheet_name='Extraction_Log', index=False)
            
            # Sheet 4: Manual QC (sample 10)
            sample = records[:min(10, len(records))]
            qc_df = pd.DataFrame([{
                "source_url": r["source_url"],
                "outage_date_extracted": r.get("outage_date"),
                "start_extracted": r.get("planned_start"),
                "end_extracted": r.get("planned_end"),
                "region_extracted": r.get("region"),
                "manual_check": "",
                "notes": ""
            } for r in sample])
            qc_df.to_excel(writer, sheet_name='Manual_QC', index=False)
        
        self.logger.info(f"Saved Excel: {excel_path}")
    
    def _create_summary_sheet(self, writer, records: List[Dict]):
        """Create summary statistics sheet"""
        verified = sum(1 for r in records if r.get("verification_status") == "VERIFIED")
        review = sum(1 for r in records if r.get("verification_status") == "REVIEW_REQUIRED")
        failed = sum(1 for r in records if r.get("verification_status") == "FAILED")
        
        unique_dates = len(set(r.get("outage_date") for r in records if r.get("outage_date")))
        unique_regions = len(set(r.get("region") for r in records if r.get("region")))
        
        # Count by region
        region_counts = {}
        for r in records:
            reg = r.get("region", "Unknown")
            region_counts[reg] = region_counts.get(reg, 0) + 1
        
        summary_data = [
            ["Metric", "Value"],
            ["Collection start", self.TARGET_START_DATE],
            ["Collection end", datetime.now().strftime("%Y-%m-%d")],
            ["Total records", len(records)],
            ["Verified", verified],
            ["Review required", review],
            ["Failed", failed],
            ["Unique outage dates", unique_dates],
            ["Unique regions", unique_regions],
            ["", ""],
            ["Region", "Count"]
        ]
        
        for region, count in sorted(region_counts.items(), key=lambda x: x[1], reverse=True):
            summary_data.append([region, count])
        
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Summary', index=False, header=False)
    
    def print_final_report(self, records: List[Dict]):
        """PHASE 6: Print terminal summary"""
        verified = sum(1 for r in records if r.get("verification_status") == "VERIFIED")
        review = sum(1 for r in records if r.get("verification_status") == "REVIEW_REQUIRED")
        failed = sum(1 for r in records if r.get("verification_status") == "FAILED")
        
        unique_dates = len(set(r.get("outage_date") for r in records if r.get("outage_date")))
        unique_regions = len(set(r.get("region") for r in records if r.get("region")))
        
        print("\n" + "="*60)
        print("       STEG OFFICIAL ELECTRICITY OUTAGE DATA")
        print("="*60)
        print(f"\nSource: {self.BASE_URL}")
        print(f"Period: {self.TARGET_START_DATE} → {datetime.now().strftime('%Y-%m-%d')}")
        print(f"\nOutage announcements: {len(records)}")
        print(f"Verified: {verified}")
        print(f"Review required: {review}")
        print(f"Failed: {failed}")
        print(f"\nUnique outage dates: {unique_dates}")
        print(f"Unique regions: {unique_regions}")
        print(f"\nRecords with complete date/time: {verified}/{len(records)} ({100*verified//len(records) if records else 0}%)")
        
        # Data feasibility
        print("\n" + "="*60)
        print("DATA FEASIBILITY FOR SUPERVISED ML")
        print("="*60)
        print(f"Historical observations: {len(records)}")
        print(f"Unique dates: {unique_dates}")
        print(f"Regions: {unique_regions}")
        
        if len(records) >= 100 and unique_dates >= 15:
            conclusion = "SUFFICIENT FOR INITIAL SUPERVISED MODELING"
        else:
            conclusion = "INSUFFICIENT FOR RELIABLE SUPERVISED MODELING"
        
        print(f"\nConclusion: {conclusion}")
        
        print("\n" + "="*60)
        print("OUTPUT FILES")
        print("="*60)
        print(f"Excel: data/processed/steg_outages.xlsx")
        print(f"CSV: data/processed/steg_outages.csv")
        print(f"Raw JSON: data/raw/steg_outages_raw.json")
        print("="*60 + "\n")


def main():
    """Entry point"""
    # Determine project root
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    
    crawler = STEGCrawler(project_root)
    crawler.run()


if __name__ == "__main__":
    main()
