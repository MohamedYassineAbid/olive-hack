"""
Data feasibility verification script.

Run this locally (not in a sandboxed/offline environment) to answer the
one question the initial feasibility report could not confirm directly:
how many real days of electricity-incident history does incident.tn
actually have?

No API key needed for either service.

Usage:
    pip install requests
    python verify_data_feasibility.py

Outputs:
    - Console summary answering the go/no-go question for supervised ML
    - Raw JSON responses saved to ../data/raw/ for inspection
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

INCIDENT_BASE = "https://api.incident.tn/api/v1"
METEO_ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# A few governorate capitals to sanity-check weather coverage against.
# (lat, lon) approximate.
TEST_LOCATIONS = {
    "Tunis": (36.8065, 10.1815),
    "Sfax": (34.7406, 10.7603),
    "Sousse": (35.8256, 10.6084),
}


def get_json(url, params=None, label=""):
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if label:
        with open(RAW_DIR / f"{label}.json", "w") as f:
            json.dump(data, f, indent=2)
    return data


def check_incident_history():
    print("=" * 70)
    print("1. incident.tn /history — electricity, requesting max window (365d)")
    print("=" * 70)
    try:
        data = get_json(
            f"{INCIDENT_BASE}/history",
            params={"type": "electricity", "days": 365},
            label="incident_history_electricity_365d",
        )
    except requests.HTTPError as e:
        print(f"  Request failed: {e}")
        return None

    rows = data.get("data", {}).get("rows", [])
    if not rows:
        print("  No rows returned at all. Either the endpoint shape differs "
              "from the schema, or there is genuinely no data yet.")
        return None

    days = sorted({r["day"] for r in rows})
    regions = sorted({r["region"] for r in rows})
    nonzero_down_rows = [r for r in rows if r.get("reports_down", 0) > 0]
    total_down_reports = sum(r.get("reports_down", 0) for r in rows)

    print(f"  Total rows returned:         {len(rows)}")
    print(f"  Distinct calendar days:      {len(days)}")
    print(f"  Earliest day in response:    {days[0] if days else 'n/a'}")
    print(f"  Latest day in response:      {days[-1] if days else 'n/a'}")
    print(f"  Distinct governorates seen:  {len(regions)} -> {regions}")
    print(f"  Rows with reports_down > 0:  {len(nonzero_down_rows)} "
          f"({100 * len(nonzero_down_rows) / max(len(rows), 1):.1f}%)")
    print(f"  Total down-reports summed:   {total_down_reports}")

    # Per-day totals, to eyeball whether early days are genuinely empty
    # (= before platform launch) vs just quiet.
    by_day = defaultdict(int)
    for r in rows:
        by_day[r["day"]] += r.get("reports_down", 0)
    print("\n  Daily total 'reports_down' (electricity, all governorates):")
    for d in days:
        bar = "#" * min(by_day[d], 50)
        print(f"    {d}  {by_day[d]:>4}  {bar}")

    first_nonzero_day = next((d for d in days if by_day[d] > 0), None)
    print(f"\n  First day with ANY electricity report: {first_nonzero_day}")
    print("  -> If this is within the last few weeks of 'today', the "
          "'platform is very new' hypothesis in the feasibility report "
          "is confirmed. Everything before it is zero-padding, not "
          "real absence-of-outages, and must not be used as negative "
          "training examples.")

    return {"days": days, "regions": regions, "rows": rows}


def check_incident_analytics():
    print("\n" + "=" * 70)
    print("2. incident.tn /analytics — electricity, max window (90d)")
    print("=" * 70)
    try:
        data = get_json(
            f"{INCIDENT_BASE}/analytics",
            params={"type": "electricity"},
            label="incident_analytics_electricity",
        )
    except requests.HTTPError as e:
        print(f"  Request failed: {e}")
        return None

    a = data.get("data", {})
    window = a.get("window", {})
    totals = a.get("totals", {})
    print(f"  Window: {window.get('from')} -> {window.get('to')} "
          f"({window.get('hours')}h, bucket={window.get('bucket_hours')}h)")
    print(f"  Totals: {totals}")
    by_region = a.get("by_region", [])
    print(f"  Governorates with activity in window: {len(by_region)}")
    for r in sorted(by_region, key=lambda x: -x.get("down", 0))[:10]:
        print(f"    {r.get('region'):20s} down={r.get('down')} "
              f"reports={r.get('reports')} share={r.get('share_pct')}%")
    return a


def check_openmeteo_overlap(days_needed):
    print("\n" + "=" * 70)
    print("3. Open-Meteo historical archive — coverage check")
    print("=" * 70)
    if not days_needed:
        print("  Skipped (no incident.tn days to match against).")
        return
    start = min(days_needed)
    end = max(days_needed)
    for name, (lat, lon) in TEST_LOCATIONS.items():
        try:
            data = get_json(
                METEO_ARCHIVE_BASE,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start,
                    "end_date": end,
                    "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
                    "timezone": "auto",
                },
                label=f"meteo_archive_{name.lower()}",
            )
            n = len(data.get("daily", {}).get("time", []))
            print(f"  {name}: {n} daily records returned for {start}..{end} "
                  f"(expected {(datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1})")
        except requests.HTTPError as e:
            print(f"  {name}: request failed ({e})")


def main():
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Raw responses will be saved to: {RAW_DIR}\n")

    hist = check_incident_history()
    check_incident_analytics()
    check_openmeteo_overlap(hist["days"] if hist else None)

    print("\n" + "=" * 70)
    print("GO / NO-GO for supervised XGBoost")
    print("=" * 70)
    if hist and len(hist["days"]) >= 90:
        print("  >= 90 real days available: supervised XGBoost with a proper")
        print("  chronological train/val/test split is defensible.")
    elif hist:
        print(f"  Only ~{len(hist['days'])} calendar days of history returned.")
        print("  Recommendation: ship the rule-based / statistical hybrid")
        print("  scorer for the deadline, and re-run this script weekly —")
        print("  switch to XGBoost once this crosses ~90 real days.")
    else:
        print("  Could not determine — check the errors above.")


if __name__ == "__main__":
    sys.exit(main())
