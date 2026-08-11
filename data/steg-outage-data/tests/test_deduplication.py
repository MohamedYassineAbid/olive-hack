"""
Unit tests for deduplication logic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.deduplicator import STEGDeduplicator


def test_url_deduplication():
    dedup = STEGDeduplicator()
    
    records = [
        {"source_url": "https://steg.com.tn/news/1", "outage_date": "2026-08-06"},
        {"source_url": "https://steg.com.tn/news/1", "outage_date": "2026-08-06"},  # duplicate
        {"source_url": "https://steg.com.tn/news/2", "outage_date": "2026-08-05"}
    ]
    
    unique = dedup._deduplicate_by_url(records)
    assert len(unique) == 2


def test_logical_deduplication():
    dedup = STEGDeduplicator()
    
    records = [
        {
            "source_url": "https://steg.com.tn/news/1",
            "outage_date": "2026-08-06",
            "region": "جهة الشمال",
            "planned_start": "13:00",
            "planned_end": "16:00",
            "affected_areas": "نابل; الحمامات",
            "verification_status": "VERIFIED",
            "raw_text": "Long text here"
        },
        {
            "source_url": "https://steg.com.tn/press/1",  # Different URL
            "outage_date": "2026-08-06",                  # Same date
            "region": "جهة الشمال",                       # Same region
            "planned_start": "13:00",                     # Same start time
            "planned_end": None,                          # Less complete
            "affected_areas": None,
            "verification_status": "REVIEW_REQUIRED",
            "raw_text": "Short"
        }
    ]
    
    unique = dedup._deduplicate_by_logic(records)
    assert len(unique) == 1
    # Should keep the more complete record (first one)
    assert unique[0]["source_url"] == "https://steg.com.tn/news/1"


def test_different_times_not_duplicates():
    dedup = STEGDeduplicator()
    
    records = [
        {"outage_date": "2026-07-24", "region": "جهة الشمال", "planned_start": "11:00"},
        {"outage_date": "2026-07-24", "region": "جهة الشمال", "planned_start": "20:00"}
    ]
    
    unique = dedup._deduplicate_by_logic(records)
    assert len(unique) == 2  # Both should be kept


if __name__ == "__main__":
    test_url_deduplication()
    test_logical_deduplication()
    test_different_times_not_duplicates()
    print("✓ All deduplication tests passed")
