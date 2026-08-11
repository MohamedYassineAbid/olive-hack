# ⚡ Quick Start Guide

Get the STEG outage data in **3 simple steps**! (5 minutes)

---

## 📋 What You Need

- **Python 3.8 or higher** installed on your computer
- **Internet connection** (to download data from STEG website)

**Check if Python is installed:**
```bash
python --version
```

If you see `Python 3.8` or higher → You're good! ✅  
If not → [Download Python here](https://www.python.org/downloads/)

---

## 🚀 3 Steps to Get Data

### Step 1: Install Required Libraries

Open your terminal/command prompt and run:

```bash
cd /path/to/steg-outage-data
pip install -r requirements.txt
```

**What this does:** Installs the tools the scraper needs:
- `beautifulsoup4` - Reads web pages
- `requests` - Downloads web pages
- `pandas` - Organizes data
- `openpyxl` - Creates Excel files

**Takes:** ~1-2 minutes  
**You only need to do this once!** ✅

---

### Step 2: Run the Scraper

**Option A: Download Fresh Data from STEG Website**

```bash
python -m scraper.steg_crawler
```

**What happens:**
- Opens STEG website
- Finds all outage announcements
- Downloads them (waits politely between requests)
- Extracts data from Arabic text
- Saves to CSV, Excel, JSON

**Takes:** ~5-10 minutes (because it waits 1.5-3s between each download)  
**Result:** Files appear in `data/processed/`

---

**Option B: Re-Process Saved HTML Files** (Faster!)

If you already have HTML files in `data/raw/html/`:

```bash
python reprocess_html.py
```

**Takes:** ~10 seconds  
**Perfect for:** Testing parser changes without re-downloading

---

### Step 3: Get Your Data! 🎉

Open the results folder:

```bash
cd data/processed/
```

**You'll find 3 files:**

```
📄 steg_outages.csv     ← Open with Excel, Google Sheets, or any text editor
📊 steg_outages.xlsx    ← Open with Microsoft Excel
📋 steg_outages.json    ← Use in programming (Python, JavaScript, etc.)
```

**Double-click the Excel file to see your data!**

---

## 📊 What's in the Data?

### Excel/CSV Columns:

| Column | What It Means | Example |
|--------|---------------|---------|
| `outage_date` | Date of the outage | 2026-07-28 |
| `planned_start` | Start time (24h format) | 06:00 |
| `planned_end` | End time or "0" if unknown | 12:00 |
| `region` | Which region | جهة الشمال |
| `affected_areas` | Which cities/towns | سوسة; المنستير; صفاقس |
| `source_url` | Original STEG announcement | https://www.steg.com.tn/... |
| `published_at` | When STEG posted it | 2026-07-27 14:39 |

### Sample View in Excel:

```
| Date       | Start | End   | Region      | Areas              |
|------------|-------|-------|-------------|--------------------|
| 2026-07-21 | 06:00 | 12:00 | جهة الشمال  | سوسة; المنستير     |
| 2026-07-22 | 10:00 | 17:00 | جهة الجنوب  | قابس; مدنين        |
| 2026-07-23 | 18:00 | 22:00 | جهة صفاقس   | صفاقس المدينة      |
```

**Total:** 113 electricity outage announcements ✅

---

## 🎯 Common Use Cases

### 1. Open in Excel/Google Sheets
```bash
# Just double-click:
data/processed/steg_outages.xlsx
```

### 2. Use in Python
```python
import pandas as pd

# Load the data
df = pd.read_csv('data/processed/steg_outages.csv')

# Show first 5 records
print(df.head())

# Filter by region
north_outages = df[df['region'] == 'جهة الشمال']

# Count by region
print(df['region'].value_counts())
```

### 3. Use in JavaScript
```javascript
// Read the JSON file
const data = require('./data/processed/steg_outages.json');

// Show first record
console.log(data[0]);

// Filter by date
const julyOutages = data.filter(record => 
    record.outage_date.startsWith('2026-07')
);
```

---

## 🔧 Troubleshooting

### ❌ Error: "No module named 'beautifulsoup4'"

**Fix:**
```bash
pip install -r requirements.txt
```

---

### ❌ Error: "Permission denied"

**Fix (Linux/Mac):**
```bash
sudo pip install -r requirements.txt
```

**Fix (Windows):** Run Command Prompt as Administrator

---

### ❌ Scraper is stuck or very slow

**Normal!** The scraper waits 1.5-3 seconds between downloads to be polite to the server.

**Progress:**
- Total articles: ~113
- Time per article: ~2 seconds
- Total time: ~5-10 minutes

**See progress:** Watch the terminal - it prints each article as it downloads!

---

### ❌ "Connection timeout" or "Failed to fetch"

**Causes:**
- No internet connection
- STEG website is down
- Firewall blocking

**Fix:**
1. Check internet connection
2. Try again in a few minutes
3. Use saved HTML files instead:
   ```bash
   python reprocess_html.py
   ```

---

### ⚠️ Want fresh data without re-downloading?

**If you already ran the scraper once:**

The HTML files are saved in `data/raw/html/`

To re-process them (useful if you fixed bugs in the parser):
```bash
python reprocess_html.py
```

This is **much faster** (~10 seconds) because it doesn't re-download!

---

## 📚 Next Steps

### Want to Understand How It Works?

Read **[README.md](README.md)** - Complete explanation with diagrams!

Topics covered:
- 🔄 How web scraping works
- 🧠 How Arabic text parsing works
- 📊 Data flow from website to Excel
- 💻 Code explanation for beginners
- 🎓 Learning resources

---

### Want to Modify the Code?

**Project structure:**
```
scraper/
├── steg_crawler.py     ← Downloads pages (START HERE)
├── steg_parser.py      ← Extracts data from Arabic text
├── steg_validator.py   ← Checks data quality
└── deduplicator.py     ← Removes duplicates
```

**Each file has detailed comments explaining what it does!**

---

### Want to Run Tests?

```bash
cd tests
python -m pytest
```

Tests check:
- ✅ Date parsing works correctly
- ✅ Time parsing handles all formats
- ✅ Region extraction works
- ✅ Deduplication works

---

## 💡 Pro Tips

### Tip 1: Schedule Automatic Updates

**Linux/Mac (using cron):**
```bash
# Run every day at 2 AM
0 2 * * * cd /path/to/steg-outage-data && python -m scraper.steg_crawler
```

**Windows (using Task Scheduler):**
1. Open Task Scheduler
2. Create new task
3. Set trigger: Daily at 2 AM
4. Set action: Run `python -m scraper.steg_crawler`

---

### Tip 2: Check Data Quality

```python
import pandas as pd

df = pd.read_csv('data/processed/steg_outages.csv')

# Check for missing data
print(df.isnull().sum())

# Count records by region
print(df['region'].value_counts())

# Find records with missing end time
missing_end = df[df['planned_end'] == '0']
print(f"Records without end time: {len(missing_end)}")
```

---

### Tip 3: Export Custom Format

```python
import pandas as pd

df = pd.read_csv('data/processed/steg_outages.csv')

# Export only specific regions
north_data = df[df['region'] == 'جهة الشمال']
north_data.to_excel('north_outages_only.xlsx', index=False)

# Export only July 2026
july_data = df[df['outage_date'].str.startswith('2026-07')]
july_data.to_csv('july_2026_outages.csv', index=False)
```

---

## ✅ Checklist

Before running the scraper:
- [ ] Python 3.8+ installed
- [ ] Libraries installed (`pip install -r requirements.txt`)
- [ ] Internet connection working
- [ ] In correct directory (`cd steg-outage-data`)

After running:
- [ ] Check `data/processed/` folder
- [ ] Open `steg_outages.xlsx` in Excel
- [ ] Verify data looks correct (113 records, all Arabic text visible)

---

## 🎉 Success!

If you see files in `data/processed/` and can open the Excel file → **You did it!** 🎊

**You now have:**
- ✅ 113 structured outage records
- ✅ Clean CSV/Excel/JSON files
- ✅ Arabic text properly displayed
- ✅ All dates, times, regions extracted
- ✅ Ready to analyze or visualize!

---

## 📞 Need Help?

1. **Read error messages carefully** - they often tell you exactly what's wrong
2. **Check README.md** - Detailed explanation of everything
3. **Look at the code comments** - Every function is explained
4. **Run tests** - `cd tests && python -m pytest` to verify everything works

---

**Happy scraping! 🚀**

*Total time from zero to data: ~10 minutes*
