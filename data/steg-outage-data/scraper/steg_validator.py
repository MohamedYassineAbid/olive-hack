"""
STEG Validator — Quality control for extracted outage data
Enforces 8 data quality rules and generates unique IDs
"""

import re
from typing import Dict, Tuple
from urllib.parse import urlparse


class STEGValidator:
    """Validates extracted outage records against quality rules"""
    
    # Region name to code mapping
    REGION_CODES = {
        "جهة تونس الكبرى": "TUNIS",
        "جهة الشمال": "NORTH",
        "جهة الشمال الغربي": "NORTHWEST",
        "جهة الوسط": "CENTER",
        "ولاية صفاقس": "SFAX",
        "جهة الجنوب": "SOUTH",
        "جهة الجنوب الغربي": "SOUTHWEST"
    }
    
    # Outage announcement keywords
    OUTAGE_KEYWORDS = ["انقطاع الكهرباء", "القطع الدوري", "انقطاع", "كهرباء"]
    
    def __init__(self):
        self.seen_ids = set()
    
    def generate_id(self, record: Dict) -> str:
        """
        Generate deterministic unique ID
        Format: STEG-YYYY-MM-DD-REGION-HHMM
        """
        date = record.get("outage_date", "UNKNOWN")
        region = record.get("region", "UNKNOWN")
        start_time = record.get("planned_start", "0000")
        
        # Get region code
        region_code = self.REGION_CODES.get(region, "UNKNOWN")
        
        # Format time
        time_part = start_time.replace(":", "") if start_time else "0000"
        
        # Base ID
        base_id = f"STEG-{date}-{region_code}-{time_part}"
        
        # Handle collisions
        id_candidate = base_id
        counter = 2
        while id_candidate in self.seen_ids:
            id_candidate = f"{base_id}-{counter}"
            counter += 1
        
        self.seen_ids.add(id_candidate)
        return id_candidate
    
    def validate(self, record: Dict) -> Tuple[str, str]:
        """
        Apply all 8 quality rules
        Returns: (verification_status, verification_notes)
        """
        notes = []
        issues = []
        
        # Rule 1: Official STEG domain
        domain = urlparse(record.get("source_url", "")).netloc
        if "steg.com.tn" not in domain:
            return "FAILED", "Source URL not from official STEG domain"
        
        # Rule 2: Contains outage keyword
        raw_text = record.get("raw_text", "")
        if not any(kw in raw_text for kw in self.OUTAGE_KEYWORDS):
            return "FAILED", "Article does not mention electricity outage"
        
        # Rule 3: Outage date present
        if not record.get("outage_date"):
            issues.append("Outage date not found")
        
        # Rule 4: Start time present
        if not record.get("planned_start"):
            issues.append("Start time not found")
        
        # Rule 5: End time present (or note if missing)
        if not record.get("planned_end"):
            issues.append("End time not explicitly stated")
        
        # Rule 6: Region present
        if not record.get("region"):
            issues.append("Region not identified")
        
        # Rule 7: Affected areas present
        if not record.get("affected_areas"):
            issues.append("Affected areas not extracted")
        
        # Rule 8: URL/body date agreement (if date in URL)
        url = record.get("source_url", "")
        date_in_url = re.search(r'(\d{2})(\d{2})(\d{4})$', url)
        if date_in_url and record.get("outage_date"):
            url_date = f"20{date_in_url.group(3)[-2:]}-{date_in_url.group(2)}-{date_in_url.group(1)}"
            body_date = record.get("outage_date")
            # Flexible comparison (some URLs encode differently)
            if url_date[:7] != body_date[:7]:  # Compare year-month
                notes.append(f"URL date {url_date} differs from body date {body_date}")
        
        # Determine status
        if issues:
            status = "REVIEW_REQUIRED"
            note = "; ".join(issues)
        else:
            status = "VERIFIED"
            note = "All fields extracted successfully"
        
        if notes:
            note += " | " + "; ".join(notes)
        
        return status, note
