"""
STEG Parser — Extracts structured data from Arabic outage announcements
Handles: dates, times, regions, affected areas from Arabic text
"""

import re
from datetime import datetime
from typing import Dict, Optional, List


class STEGParser:
    """Parser for Arabic electricity outage announcements"""
    
    # Arabic month names → numeric
    ARABIC_MONTHS = {
        "جانفي": "01", "فيفري": "02", "مارس": "03",
        "أفريل": "04", "ماي": "05", "جوان": "06",
        "جويلية": "07", "أوت": "08", "سبتمبر": "09",
        "أكتوبر": "10", "نوفمبر": "11", "ديسمبر": "12"
    }
    
    # Arabic ordinal numbers for time parsing
    ARABIC_HOURS = {
        "الواحدة": 1, "الثانية": 2, "الثالثة": 3, "الرابعة": 4,
        "الخامسة": 5, "السادسة": 6, "السابعة": 7, "الثامنة": 8,
        "التاسعة": 9, "العاشرة": 10, "الحادية عشر": 11, "الحادية عشرة": 11,
        "الثانية عشر": 12, "الثانية عشرة": 12
    }
    
    # Known STEG regions (including synonyms)
    REGIONS = [
        "جهة تونس الكبرى", "جهة الشمال", "جهة الشمال الغربي",
        "جهة الوسط", "ولاية صفاقس", "جهة صفاقس", 
        "جهة الجنوب", "جهة الجنوب الغربي"
    ]
    
    def parse_date(self, text: str) -> Optional[str]:
        """
        Extract outage date from Arabic or numeric format
        Examples:
          "06 أوت 2026" → "2026-08-06"
          "24/07/2026" → "2026-07-24"
        """
        # Try numeric format first: DD/MM/YYYY
        numeric = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if numeric:
            day, month, year = numeric.groups()
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        # Try Arabic format: DD MONTH YYYY
        for ar_month, num_month in self.ARABIC_MONTHS.items():
            pattern = rf'(\d{{1,2}})\s+{ar_month}\s+(\d{{4}})'
            match = re.search(pattern, text)
            if match:
                day, year = match.groups()
                return f"{year}-{num_month}-{day.zfill(2)}"
        
        return None
    
    def parse_time(self, text: str, is_end_time: bool = False) -> Optional[str]:
        """
        Extract time from Arabic or numeric format
        Examples:
          "13:00" → "13:00"
          "الساعة الواحدة بعد الزوال" → "13:00"
          "منتصف النهار" → "12:00"
          "منتصف الليل" → "00:00"
          "العاشرة ليلا" → "22:00"
        """
        # Check for special cases first (including common typos)
        if "منتصف النهار" in text or "منتصف النهر" in text:  # Handle typo: النهر → النهار
            return "12:00"
        if "منتصف الليل" in text:
            return "00:00"
        
        # Try numeric format: HH:MM or HH:MM
        numeric = re.search(r'(\d{1,2})[:\s]?(\d{2})?', text)
        if numeric:
            hour = int(numeric.group(1))
            minute = numeric.group(2) or "00"
            # Validate hour
            if 0 <= hour <= 23:
                return f"{hour:02d}:{minute}"
        
        # Try Arabic ordinal + context
        afternoon_markers = ["بعد الزوال", "مساء", "عصرا"]
        morning_markers = ["صباحا", "في الصباح"]
        night_markers = ["ليلا", "ليلة", "في الليل"]
        
        is_pm = any(marker in text for marker in afternoon_markers)
        is_am = any(marker in text for marker in morning_markers)
        is_night = any(marker in text for marker in night_markers)
        
        for ar_hour, hour_num in self.ARABIC_HOURS.items():
            if ar_hour in text:
                # Adjust for PM/night if needed
                if (is_pm or is_night) and hour_num < 12:
                    hour_num += 12
                elif is_am and hour_num == 12:
                    hour_num = 0
                return f"{hour_num:02d}:00"
        
        return None
    
    def parse_time_range(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract start and end times from range expressions
        Examples: 
          "بين الساعة الواحدة والساعة الرابعة بعد الزوال" → ("13:00", "16:00")
          "بين الساعة السادسة صباحا والساعة منتصف النهار" → ("06:00", "12:00")
        """
        # Look for "بين ... و ..." pattern
        if 'بين' in text and 'و' in text:
            # Find the بين ... و ... section
            bain_idx = text.find('بين')
            if bain_idx >= 0:
                # Get text after بين
                after_bain = text[bain_idx + 3:].strip()
                
                # Split on و to separate start and end
                # Use والساعة or و الساعة as separator
                if 'والساعة' in after_bain:
                    parts = after_bain.split('والساعة', 1)
                elif 'و الساعة' in after_bain:
                    parts = after_bain.split('و الساعة', 1)
                elif 'و' in after_bain:
                    parts = after_bain.split('و', 1)
                else:
                    parts = []
                
                if len(parts) == 2:
                    start_text = parts[0].strip()
                    end_text = parts[1].strip()
                    
                    # Remove trailing commas, periods, etc
                    for char in ['،', '.', '؛']:
                        if start_text.endswith(char):
                            start_text = start_text[:-1].strip()
                        if end_text.endswith(char):
                            end_text = end_text[:-1].strip()
                    
                    # Parse each part
                    start_time = self.parse_time(start_text)
                    end_time = self.parse_time(end_text)
                    
                    return start_time, end_time
        
        # Fallback: look for any two numeric times
        times = re.findall(r'(\d{1,2})[:\s]?(\d{2})', text)
        if len(times) >= 2:
            start = f"{int(times[0][0]):02d}:{times[0][1]}"
            end = f"{int(times[1][0]):02d}:{times[1][1]}"
            return start, end
        
        return None, None
    
    def parse_region(self, title: str, body: str) -> Optional[str]:
        """
        Extract region from title or body
        Example: "إشعار بانقطاع الكهرباء - جهة الشمال" → "جهة الشمال"
        Normalizes "ولاية صفاقس" to "جهة صفاقس"
        """
        # Try title first (most reliable)
        for region in self.REGIONS:
            if region in title:
                # Normalize Sfax variants
                if region in ["ولاية صفاقس", "جهة صفاقس"]:
                    return "جهة صفاقس"
                return region
        
        # Fallback to body
        for region in self.REGIONS:
            if region in body:
                # Normalize Sfax variants
                if region in ["ولاية صفاقس", "جهة صفاقس"]:
                    return "جهة صفاقس"
                return region
        
        return None
    
    def parse_affected_areas(self, text: str) -> List[str]:
        """
        Extract list of affected geographical areas
        Looks for section after "المناطق التالية" or similar markers
        """
        areas = []
        
        # Find the areas section
        markers = ["المناطق التالية", "المناطق المعنية", "القائمة التالية"]
        start_idx = -1
        
        for marker in markers:
            idx = text.find(marker)
            if idx >= 0:
                start_idx = idx + len(marker)
                break
        
        if start_idx < 0:
            return areas
        
        # Extract text after marker until next major section
        section_text = text[start_idx:start_idx+2000]
        
        # Stop at common ending markers
        end_markers = ["لذا،", "هذه القائمة", "مع عودة", "للتبليغ", "وتتقدم"]
        end_idx = len(section_text)
        for marker in end_markers:
            idx = section_text.find(marker)
            if idx > 0 and idx < end_idx:
                end_idx = idx
        
        section_text = section_text[:end_idx]
        
        # Split by common separators and newlines
        lines = re.split(r'[\n\r]+', section_text)
        
        for line in lines:
            line = line.strip()
            # Filter: Arabic text, reasonable length, not boilerplate
            if line and 2 <= len(line) <= 50:
                # Check if mostly Arabic
                arabic_chars = sum(1 for c in line if '\u0600' <= c <= '\u06FF')
                if arabic_chars > len(line) * 0.5:
                    # Remove bullets, numbers, extra whitespace
                    line = re.sub(r'^[-•*\d.\s]+', '', line)
                    line = re.sub(r'\s+', ' ', line)
                    if len(line) > 2:
                        areas.append(line)
        
        return areas
    
    def parse_article(self, url: str, title: str, body: str, published_at: str) -> Dict:
        """
        Main entry point: parse complete article
        Returns dictionary with all extracted fields
        """
        result = {
            "source_url": url,
            "source_title": title,
            "raw_text": body[:2000],  # Keep first 2000 chars
            "published_at": self._normalize_published_at(published_at),
            "outage_date": None,
            "planned_start": None,
            "planned_end": None,
            "region": None,
            "affected_areas": None,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Extract date
        result["outage_date"] = self.parse_date(body)
        
        # Extract time range
        start, end = self.parse_time_range(body)
        result["planned_start"] = start
        # Set end to "0" if not found (as per user requirement)
        result["planned_end"] = end if end else "0"
        
        # Extract region
        result["region"] = self.parse_region(title, body)
        
        # Extract affected areas
        areas = self.parse_affected_areas(body)
        if areas:
            result["affected_areas"] = "; ".join(areas)
        
        return result
    
    def _normalize_published_at(self, pub_str: str) -> Optional[str]:
        """
        Convert "DD/MM/YYYY - HH:MM" to "YYYY-MM-DD HH:MM"
        """
        match = re.search(r'(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2}):(\d{2})', pub_str)
        if match:
            day, month, year, hour, minute = match.groups()
            return f"{year}-{month}-{day} {hour}:{minute}"
        return None
