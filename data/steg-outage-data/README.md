# 🔌 STEG Electricity Outage Data Scraper

A complete web scraper that automatically collects electricity outage announcements from the STEG website and converts them into clean, structured data (CSV, Excel, JSON).

**Perfect for beginners!** This guide explains everything step-by-step with easy-to-understand diagrams.

---

## 📚 Table of Contents

1. [What Does This Do?](#what-does-this-do)
2. [How It Works - Complete Methodology](#how-it-works---complete-methodology)
3. [Project Structure](#project-structure)
4. [Data Output](#data-output)
5. [Installation & Usage](#installation--usage)
6. [Understanding the Code](#understanding-the-code)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 What Does This Do?

This scraper automatically:
1. **Visits** the STEG website (Tunisia's electricity company)
2. **Finds** all electricity outage announcements (in Arabic)
3. **Extracts** important information like:
   - When is the outage? (date)
   - What time does it start? 
   - What time does it end?
   - Which region? (جهة الشمال, جهة الجنوب, etc.)
   - Which areas are affected?
4. **Saves** everything in easy-to-use formats (Excel, CSV, JSON)

**Result**: Instead of reading 113 Arabic announcements manually, you get a clean spreadsheet! 📊

---

## 🔄 How It Works - Complete Methodology

### The Big Picture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐      ┌──────────────┐
│   STEG      │      │   Download   │      │   Extract   │      │   Save to    │
│  Website    │ ───> │   HTML       │ ───> │   Data      │ ───> │   Files      │
│  (Arabic)   │      │   Pages      │      │   (Parse)   │      │ (CSV/Excel)  │
└─────────────┘      └──────────────┘      └─────────────┘      └──────────────┘
```

### Step-by-Step Process

#### 📥 **STEP 1: Discovery** (Finding Articles)

```
STEG Website
    ↓
┌─────────────────────────────────────────┐
│  News Listing Page                      │
│  ┌─────────────────────────────────┐   │
│  │ إشعار بانقطاع الكهرباء - جهة...  │   │  ← Outage announcement ✅
│  ├─────────────────────────────────┤   │
│  │ مناظرة خارجية للإنتداب...       │   │  ← Job posting ❌ (filtered)
│  ├─────────────────────────────────┤   │
│  │ إشعار بانقطاع الكهرباء - جهة...  │   │  ← Outage announcement ✅
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
    ↓ Filter: Keep only "إشعار بانقطاع الكهرباء"
    ↓
┌─────────────────────────────────────────┐
│  Filtered List: 113 outage articles    │
└─────────────────────────────────────────┘
```

**What happens:**
- Opens STEG news page (page 1, 2, 3, etc.)
- Looks at each article title
- **Filters**: Only keeps articles with "إشعار بانقطاع الكهرباء" (outage announcement)
- **Ignores**: Job postings, studies, other news
- Collects all article URLs

---

#### 📥 **STEP 2: Download** (Getting Full Content)

```
For each article URL:
    ↓
┌─────────────────────────────────────────┐
│  Download HTML page                     │
│  (Wait 1.5-3 seconds to be polite)     │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│  Save to: data/raw/html/abc123.html    │
│  (Backup for later)                     │
└─────────────────────────────────────────┘
```

**What happens:**
- Downloads the full announcement page
- Waits 1.5-3 seconds between downloads (to be nice to the server)
- Saves HTML to `data/raw/html/` folder
- Why save HTML? So we can re-process later without re-downloading!

---

#### 🔍 **STEP 3: Extract Data** (Parsing Arabic Text)

This is the most complex part! The Arabic text looks like this:

```
في إطار الحفاظ على سلامة و ديمومة المنظومة الكهربائية،
تعلم الشركة التونسية للكهرباء و الغاز أنّه قد يتمّ اللجوء إلى
القطع الدوري للكهرباء اليوم الثلاثاء 21 جويلية 2026،
خلال الفترة المتراوحة بين الساعة السادسة صباحا والساعة منتصف النهار،
وعلى فترات متقطّعة، على مستوى المناطق التالية:
سوسة، المنستير، صفاقس
```

**The parser extracts:**

```
┌──────────────────────────────────────┐
│  Arabic Text (Announcement)          │
└──────────────────────────────────────┘
           ↓
    ┌──────┴──────┐
    │   PARSER    │
    └──────┬──────┘
           ↓
┌──────────────────────────────────────┐
│  Structured Data:                    │
│  • Date: 2026-07-21                  │
│  • Start: 06:00                      │
│  • End: 12:00                        │
│  • Region: جهة الوسط                 │
│  • Areas: سوسة; المنستير; صفاقس     │
└──────────────────────────────────────┘
```

##### 🗓️ **Date Parsing** (Finding the Date)

```python
Input:  "الثلاثاء 21 جويلية 2026"
        
Step 1: Find day number → "21"
Step 2: Find Arabic month → "جويلية"
Step 3: Convert to number → "07" (July)
Step 4: Find year → "2026"

Output: "2026-07-21" ✅
```

**Supported formats:**
- ✅ "21 جويلية 2026" (Arabic month)
- ✅ "21/07/2026" (Numeric)

---

##### 🕐 **Time Parsing** (Finding Start/End Times)

The parser handles Arabic time expressions:

```
┌─────────────────────────────┬─────────────┐
│  Arabic Expression          │  Parsed As  │
├─────────────────────────────┼─────────────┤
│  الساعة السادسة صباحا       │  06:00      │ (6 AM)
│  منتصف النهار               │  12:00      │ (noon)
│  منتصف النهر (typo)         │  12:00      │ (noon - typo handled!)
│  الساعة الرابعة مساء        │  16:00      │ (4 PM)
│  العاشرة ليلا                │  22:00      │ (10 PM)
│  منتصف الليل                │  00:00      │ (midnight)
└─────────────────────────────┴─────────────┘
```

**Time Range Parsing:**

```
Input: "بين الساعة السادسة صباحا والساعة منتصف النهار"

Step 1: Find "بين" (between)
Step 2: Split on "و" (and)
        → Part 1: "الساعة السادسة صباحا"
        → Part 2: "الساعة منتصف النهار"
        
Step 3: Parse each part
        → "السادسة صباحا" → 06:00 (6 + morning = 6 AM)
        → "منتصف النهار" → 12:00 (special case: noon)
        
Output: Start=06:00, End=12:00 ✅
```

---

##### 📍 **Region Extraction** (Which Region?)

```
Title: "إشعار بانقطاع الكهرباء - جهة الشمال - 10:00 22/07/2026"
                                      └────┬────┘
                                    Extract this!
                                           ↓
Known regions list:
  • جهة الشمال ✅
  • جهة الجنوب
  • جهة الوسط
  • جهة صفاقس
  • جهة تونس الكبرى
  
Output: "جهة الشمال" ✅
```

**Special handling:**
- "ولاية صفاقس" → Normalized to "جهة صفاقس" ✅

---

##### 🏘️ **Areas Extraction** (Which Cities/Towns?)

```
Arabic Text:
"...على مستوى المناطق التالية:
سوسة
المنستير
صفاقس
القيروان"

Step 1: Find marker "المناطق التالية" (following areas)
Step 2: Extract lines after marker
Step 3: Filter: Keep only Arabic text, reasonable length
Step 4: Clean up bullets, numbers

Output: "سوسة; المنستير; صفاقس; القيروان" ✅
```

---

#### ✅ **STEP 4: Validation** (Quality Check)

```
For each record:
    ↓
┌────────────────────────────────────┐
│  8-Rule Validation Check           │
│                                    │
│  ✅ Has valid date?                │
│  ✅ Has start time?                │
│  ✅ Has region?                    │
│  ✅ Region in known list?          │
│  ✅ Has affected areas?            │
│  ✅ Date not in past?              │
│  ✅ Times logical?                 │
│  ✅ Not duplicate?                 │
└────────────────────────────────────┘
    ↓
  PASS → Keep ✅
  FAIL → Review/Log ⚠️
```

---

#### 🔄 **STEP 5: Deduplication** (Remove Duplicates)

```
Method 1: URL Check
─────────────────────
Same URL = Duplicate ✅

Method 2: Content Hash
──────────────────────
Hash(date + region + start_time + areas)
  ↓
If hash exists → Duplicate ✅
```

**Example:**
```
Record A: 2026-07-21, جهة الشمال, 06:00, "سوسة; المنستير"
Record B: 2026-07-21, جهة الشمال, 06:00, "سوسة; المنستير"
                                  ↓
                           Same hash → Keep only one
```

---

#### 💾 **STEP 6: Export** (Save to Files)

```
113 Clean Records
    ↓
┌───────────────────────────────────────┐
│  Export to 3 Formats:                 │
│                                       │
│  📄 CSV  → steg_outages.csv          │
│  📊 Excel → steg_outages.xlsx        │
│  📋 JSON → steg_outages.json         │
└───────────────────────────────────────┘
```

**Excel Format:**

```
| outage_date | planned_start | planned_end | region      | affected_areas       |
|-------------|---------------|-------------|-------------|----------------------|
| 2026-07-21  | 06:00         | 12:00       | جهة الشمال | سوسة; المنستير; صفاقس |
| 2026-07-22  | 10:00         | 17:00       | جهة الجنوب | قابس; مدنين          |
```

---

## 📁 Project Structure

```
steg-outage-data/
│
├── 📊 data/
│   ├── processed/              ← YOUR RESULTS ARE HERE!
│   │   ├── steg_outages.csv    ← Open in Excel/Google Sheets
│   │   ├── steg_outages.xlsx   ← Open in Excel
│   │   └── steg_outages.json   ← Use in programming
│   │
│   └── raw/
│       ├── html/               ← 120 saved web pages
│       └── steg_outages_raw.json
│
├── 🔧 scraper/                  ← The code that does the work
│   ├── steg_crawler.py         ← Main: Downloads pages
│   ├── steg_parser.py          ← Extracts data from Arabic text
│   ├── steg_validator.py       ← Checks data quality
│   └── deduplicator.py         ← Removes duplicates
│
├── ✅ tests/                    ← Code tests (optional to run)
│
├── 📝 README.md                 ← You are here!
├── 📝 QUICK_START.md            ← How to run (3 steps)
│
└── ⚙️ Other files:
    ├── reprocess_html.py       ← Re-process saved HTML files
    └── requirements.txt        ← List of needed libraries
```

---

## 📊 Data Output

### CSV/Excel Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `source_url` | URL | Original announcement page | https://www.steg.com.tn/... |
| `source_title` | Text | Title of announcement | "إشعار بانقطاع الكهرباء..." |
| `published_at` | DateTime | When STEG posted it | "2026-07-27 14:39" |
| `outage_date` | Date | Date of outage | "2026-07-28" |
| `planned_start` | Time | Start time (24-hour) | "06:00" |
| `planned_end` | Time | End time or "0" if unknown | "12:00" or "0" |
| `region` | Text | Which region | "جهة الشمال" |
| `affected_areas` | Text | Cities/towns (semicolon-separated) | "سوسة; المنستير; صفاقس" |
| `scraped_at` | DateTime | When we extracted it | "2026-08-11 15:00:30" |

### Sample Data

```csv
outage_date,planned_start,planned_end,region,affected_areas
2026-07-21,06:00,12:00,جهة الشمال,"سوسة; المنستير"
2026-07-22,10:00,17:00,جهة الجنوب,"قابس; مدنين"
2026-07-23,18:00,22:00,جهة صفاقس,"صفاقس المدينة; ساقية الزيت"
```

---

## 🚀 Installation & Usage

**See [QUICK_START.md](QUICK_START.md) for step-by-step instructions!**

Quick overview:
```bash
# 1. Install Python libraries
pip install -r requirements.txt

# 2. Run the scraper
python -m scraper.steg_crawler
```

**Or re-process saved HTML files:**
```bash
python reprocess_html.py
```

---

## 💡 Understanding the Code

### Main Files Explained (for beginners)

#### 1. `steg_crawler.py` - The Downloader

**What it does:** Goes to STEG website and downloads pages

**Key parts:**
```python
# This finds all article links
def discover_articles():
    # Goes through pages: page=0, page=1, etc.
    # Looks at each article
    # Keeps only "إشعار بانقطاع الكهرباء"
    
# This downloads one article
def download_and_parse(url):
    # Gets the HTML
    # Saves it to data/raw/html/
    # Calls the parser to extract data
```

---

#### 2. `steg_parser.py` - The Arabic Text Expert

**What it does:** Reads Arabic text and extracts structured data

**Key parts:**
```python
# Parse date from Arabic
def parse_date(text):
    # "21 جويلية 2026" → "2026-07-21"
    
# Parse time expressions
def parse_time(text):
    # "منتصف النهار" → "12:00"
    # "العاشرة ليلا" → "22:00"
    
# Parse time ranges
def parse_time_range(text):
    # "بين السادسة صباحا والساعة منتصف النهار"
    # → start="06:00", end="12:00"
    
# Find region
def parse_region(title, body):
    # Looks for "جهة الشمال", "جهة الجنوب", etc.
    
# Extract affected areas
def parse_affected_areas(text):
    # Finds the list of cities/towns
```

---

#### 3. `steg_validator.py` - The Quality Checker

**What it does:** Makes sure data is valid

**8 Validation Rules:**
1. ✅ Has a date?
2. ✅ Has start time?
3. ✅ Has region?
4. ✅ Region is known? (not random text)
5. ✅ Has affected areas?
6. ✅ Date makes sense? (not year 1900)
7. ✅ Times are logical? (start before end)
8. ✅ Not duplicate?

---

#### 4. `deduplicator.py` - The Duplicate Finder

**What it does:** Removes duplicate announcements

**How:**
- Creates a unique "fingerprint" for each record
- Fingerprint = hash of (date + region + time + areas)
- If two records have same fingerprint → keep only one

---

## 🐛 Troubleshooting

### Common Issues

#### Problem: "No module named 'beautifulsoup4'"
**Solution:**
```bash
pip install -r requirements.txt
```

#### Problem: Scraper is very slow
**Reason:** It waits 1.5-3 seconds between downloads (to be polite)  
**Solution:** This is normal! For 113 articles ≈ 5-10 minutes

#### Problem: "Connection timeout"
**Solution:** 
- Check your internet connection
- STEG website might be down - try later

#### Problem: Want to re-process without re-downloading?
**Solution:**
```bash
python reprocess_html.py
```
This uses the saved HTML files in `data/raw/html/`

---

## 🎓 Learning Resources

### For Absolute Beginners

**Python Basics:**
- [Learn Python in 10 Minutes](https://www.stavros.io/tutorials/python/)
- [Python for Beginners](https://www.python.org/about/gettingstarted/)

**Web Scraping:**
- [Beautiful Soup Documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [Web Scraping Tutorial](https://realpython.com/beautiful-soup-web-scraper-python/)

**Arabic Text Processing:**
- [Unicode in Python](https://docs.python.org/3/howto/unicode.html)
- This project is a great real example!

---

## ✨ Key Features

✅ **Beginner-Friendly** - Clear code with comments  
✅ **Robust** - Handles typos, variations, missing data  
✅ **Smart** - Filters non-outage content automatically  
✅ **Polite** - Waits between requests  
✅ **Reproducible** - Saves HTML for later re-processing  
✅ **Multi-Format** - CSV, Excel, JSON outputs  
✅ **Arabic Support** - Proper UTF-8 encoding  
✅ **Tested** - Unit tests for critical functions  

---

## 📈 Statistics

- **113** outage announcements collected
- **5** regions covered
- **120** HTML pages saved
- **1,105** lines of Python code
- **8** validation rules
- **2-pass** deduplication
- **100%** UTF-8 Arabic support

---

## 🤝 Credits

**Developed for:** Olive Hackathon 2026  
**Data Source:** [STEG Official Website](https://www.steg.com.tn)  
**Language:** Python 3.12+  
**Location:** Tunisia 🇹🇳

---

## 📝 License

This project is for educational purposes. Please respect STEG's terms of service and use the data responsibly.

---

**Questions?** Read the code comments - they explain everything step-by-step! 💡
