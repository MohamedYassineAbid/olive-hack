"""
Unit tests for Arabic time parsing
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.steg_parser import STEGParser


def test_numeric_time():
    parser = STEGParser()
    
    assert parser.parse_time("13:00") == "13:00"
    assert parser.parse_time("9:30") == "09:30"
    assert parser.parse_time("20:45") == "20:45"


def test_arabic_time():
    parser = STEGParser()
    
    # With afternoon marker
    assert parser.parse_time("الساعة الواحدة بعد الزوال") == "13:00"
    assert parser.parse_time("الساعة الرابعة بعد الزوال") == "16:00"
    
    # With morning marker
    assert parser.parse_time("الساعة الحادية عشر صباحا") == "11:00"


def test_time_range():
    parser = STEGParser()
    
    text = "بين الساعة الواحدة والساعة الرابعة بعد الزوال"
    start, end = parser.parse_time_range(text)
    assert start == "13:00"
    assert end == "16:00"


if __name__ == "__main__":
    test_numeric_time()
    test_arabic_time()
    test_time_range()
    print("✓ All time parsing tests passed")
