"""
Unit tests for region extraction
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.steg_parser import STEGParser


def test_region_from_title():
    parser = STEGParser()
    
    title = "إشعار بانقطاع الكهرباء - جهة الشمال - 13:00 06/08/2026"
    region = parser.parse_region(title, "")
    assert region == "جهة الشمال"
    
    title2 = "إشعار بانقطاع الكهرباء - جهة تونس الكبرى - 12:30 05/08/2026"
    region2 = parser.parse_region(title2, "")
    assert region2 == "جهة تونس الكبرى"


def test_all_regions():
    parser = STEGParser()
    
    expected_regions = [
        "جهة تونس الكبرى", "جهة الشمال", "جهة الشمال الغربي",
        "جهة الوسط", "ولاية صفاقس", "جهة الجنوب", "جهة الجنوب الغربي"
    ]
    
    assert len(parser.REGIONS) == 7
    assert all(r in parser.REGIONS for r in expected_regions)


if __name__ == "__main__":
    test_region_from_title()
    test_all_regions()
    print("✓ All region parsing tests passed")
