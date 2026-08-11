"""
Unit tests for Arabic date parsing
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.steg_parser import STEGParser


def test_numeric_date():
    parser = STEGParser()
    
    # DD/MM/YYYY format
    assert parser.parse_date("06/08/2026") == "2026-08-06"
    assert parser.parse_date("24/07/2026") == "2026-07-24"
    assert parser.parse_date("1/7/2026") == "2026-07-01"


def test_arabic_date():
    parser = STEGParser()
    
    # DD MONTH YYYY format
    assert parser.parse_date("06 أوت 2026") == "2026-08-06"
    assert parser.parse_date("24 جويلية 2026") == "2026-07-24"
    assert parser.parse_date("1 سبتمبر 2026") == "2026-09-01"


def test_date_in_sentence():
    parser = STEGParser()
    
    text = "اليوم الخميس 06 أوت 2026، خلال الفترة المتراوحة"
    assert parser.parse_date(text) == "2026-08-06"


if __name__ == "__main__":
    test_numeric_date()
    test_arabic_date()
    test_date_in_sentence()
    print("✓ All date parsing tests passed")
