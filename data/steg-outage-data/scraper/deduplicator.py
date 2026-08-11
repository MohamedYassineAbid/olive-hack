"""
STEG Deduplicator — Removes duplicate outage announcements
Two-pass approach: URL dedup + logical dedup
"""

from typing import List, Dict
from collections import defaultdict


class STEGDeduplicator:
    """Identifies and removes duplicate outage records"""
    
    def deduplicate(self, records: List[Dict]) -> List[Dict]:
        """
        Remove duplicates in two passes
        Returns: list of unique records
        """
        # Pass 1: Remove exact URL duplicates
        unique_by_url = self._deduplicate_by_url(records)
        
        # Pass 2: Remove logical duplicates (same date+region+time)
        unique_records = self._deduplicate_by_logic(unique_by_url)
        
        return unique_records
    
    def _deduplicate_by_url(self, records: List[Dict]) -> List[Dict]:
        """Remove records with identical source URLs"""
        seen_urls = set()
        unique = []
        
        for record in records:
            url = record.get("source_url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(record)
        
        return unique
    
    def _deduplicate_by_logic(self, records: List[Dict]) -> List[Dict]:
        """
        Remove logical duplicates (same date+region+start time)
        When duplicates found, keep the one with more complete data
        """
        # Group by logical key
        groups = defaultdict(list)
        
        for record in records:
            date = record.get("outage_date", "")
            region = record.get("region", "")
            start = record.get("planned_start", "")
            
            key = (date, region, start)
            groups[key].append(record)
        
        # Keep best record from each group
        unique = []
        for key, group in groups.items():
            if len(group) == 1:
                unique.append(group[0])
            else:
                # Multiple records with same key → keep most complete
                best = self._select_best_record(group)
                unique.append(best)
        
        return unique
    
    def _select_best_record(self, records: List[Dict]) -> Dict:
        """
        Select the most complete record from duplicates
        Score based on: has end time, has areas, verification status
        """
        scored = []
        
        for record in records:
            score = 0
            
            # +1 for each present optional field
            if record.get("planned_end"):
                score += 2
            if record.get("affected_areas"):
                score += 2
            if record.get("verification_status") == "VERIFIED":
                score += 1
            
            # Longer raw text = more complete
            score += min(len(record.get("raw_text", "")), 500) // 100
            
            scored.append((score, record))
        
        # Return highest scoring
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
