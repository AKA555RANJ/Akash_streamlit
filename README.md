# Syllabi Scrapers

This repo contains two web scrapers that download course syllabi from university public repositories and save the metadata to CSV/JSON files.

| Scraper | University | Website |
|---------|-----------|---------|
| **UConn** | University of Connecticut | https://syllabus.uconn.edu/public/ |
| **OSU** | Ohio State University | OSU Syllabus site |

---

## What does it do?

Each scraper:
1. Visits the university's public syllabus site
2. Finds every course syllabus listed for the terms you specify
3. Saves metadata (term, class name, section, instructor, URL) to a CSV and JSON file
4. Optionally downloads the actual PDF/DOCX syllabus files to your machine

---

## Project Structure

```
Akash_streamlit/
│
├── README.md                          ← You are here
│
├── uconn_syllabi_scrapy/              ← UConn scraper (Scrapy framework)
│   ├── scrapy.cfg                     ← Scrapy project config
│   ├── requirements.txt               ← Python dependencies
│   └── uconn_syllabi_scrapy/
│       ├── settings.py                ← Crawler settings (speed, output paths)
│       ├── items.py                   ← Data fields definition
│       ├── pipelines.py               ← How data is saved (CSV, JSON, files)
│       └── spiders/
│           └── uconn_syllabi_spider.py  ← The actual scraping logic
│
├── osu_syllabi_scrapy/                ← OSU scraper (Scrapy framework)
├── osu_syllabi_scraper.py             ← OSU scraper (standalone script)
│
├── output/                            ← Created automatically when you run
│   ├── syllabi_metadata.csv
│   └── syllabi_metadata.json
│
└── syllabi_downloads/                 ← Downloaded PDF/DOCX files go here
```

---

## Quick Start: UConn Scraper

### Step 1 — Go to the project folder

```bash
cd uconn_syllabi_scrapy
```

> All `scrapy crawl` commands must be run from this folder.

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs Scrapy (the scraping framework) and its helper library.

### Step 3 — Run the scraper

**Just get the metadata list (no file downloads, fast):**
```bash
scrapy crawl uconn_syllabi -a target_terms=1258 -a no_download=1
```

**Get metadata + download the actual PDF syllabi:**
```bash
scrapy crawl uconn_syllabi -a target_terms=1258 -a target_depts=CSE
```

**Scrape everything (all terms, all departments, all downloads):**
```bash
scrapy crawl uconn_syllabi
```

### Step 4 — Check the output

After it runs, you'll find:
- `output/syllabi_metadata.csv` — spreadsheet with one row per syllabus
- `output/syllabi_metadata.json` — same data in JSON format
- `syllabi_downloads/` — the downloaded PDF files (if you didn't use `no_download=1`)

---

## Scraper Arguments

You can filter what gets scraped by passing arguments with `-a`:

| Argument | What it does | Example |
|----------|-------------|---------|
| `target_terms` | Only scrape specific term(s) | `-a target_terms=1258` |
| `target_depts` | Only scrape specific department(s) | `-a target_depts=CSE` |
| `no_download` | Skip downloading PDF files (metadata only) | `-a no_download=1` |

You can combine them and use commas for multiple values:
```bash
# Two terms, three departments, with downloads
scrapy crawl uconn_syllabi -a target_terms=1258,1252 -a target_depts=CSE,MATH,ECE

# One term, one dept, no downloads
scrapy crawl uconn_syllabi -a target_terms=1258 -a target_depts=CSE -a no_download=1
```

---

## Finding Term Codes

Term codes are the numbers that identify each semester. Common ones:

| Semester | Code |
|----------|------|
| Fall 2025 | `1258` |
| Spring 2025 | `1252` |
| Fall 2024 | `1248` |

To see all available terms, run this — it prints every term the site has:
```bash
scrapy crawl uconn_syllabi -a no_download=1 2>&1 | grep "Queuing term"
```

You can also visit https://syllabus.uconn.edu/public/search_term.php in a browser and look at the dropdown.

---

## Output Fields

Each row in the CSV/JSON contains these 7 fields:

| Field | Example value | Description |
|-------|--------------|-------------|
| `term_name` | `Fall 2025` | The semester label |
| `class_name` | `CSE 3666` | Department + course number |
| `section` | `001` | Section number (can be blank) |
| `instructor` | `Zhijie Shi` | Instructor's name |
| `syllabus_web_url` | `https://syllabus.uconn.edu/public/download.php?file=1468%7C...` | Direct download link from the website |
| `syllabus_local_filepath` | `syllabi_downloads/1258_CSE_3666_1468.pdf` | Where the file was saved on your machine |
| `syllabus_local_filename` | `1258_CSE_3666_1468.pdf` | Just the filename |

Downloaded files are named: `{term_code}_{dept}_{course_number}_{file_id}.pdf`
For example: `1258_CSE_3666_1468.pdf` = Fall 2025, CSE 3666, file ID 1468.

> If you used `no_download=1`, the `syllabus_local_filepath` and `syllabus_local_filename` fields will be empty — the web URL is still captured.

---

## How the Code Works

The scraper has two steps:

**Step 1** — Fetch the term list
Visits `search_term.php`, reads the dropdown menu, and collects all term codes and names.

**Step 2** — Fetch syllabi for each term
For each term, visits `search_term.php?term=XXXX` and reads the HTML table row by row, extracting: class name, section, instructor, and the download link.

Three pipelines then process each item:
1. **`UConnFilesPipeline`** — downloads the PDF file and names it `{term}_{dept}_{num}_{id}.pdf`
2. **`CsvExportPipeline`** — streams rows to `output/syllabi_metadata.csv`
3. **`JsonExportPipeline`** — collects all rows and writes `output/syllabi_metadata.json` when done

Key files:
- `spiders/uconn_syllabi_spider.py` — scraping logic (what pages to visit, how to parse them)
- `pipelines.py` — output logic (how to save data and files)
- `settings.py` — configuration (request speed, output directory, which pipelines are active)
- `items.py` — defines the data fields that each scraped row contains

---

## OSU Scraper

Two versions are available:

**Standalone script** (simpler, no Scrapy needed):
```bash
pip install requests beautifulsoup4 lxml tenacity tqdm
python osu_syllabi_scraper.py --campuses COL --terms SP2026 --subjects CSE --no-download
```

**Scrapy version:**
```bash
cd osu_syllabi_scrapy
pip install -r requirements.txt
scrapy crawl osu_syllabi -a target_campuses=COL -a target_terms=SP2026 -a target_subjects=CSE
```

> **Note:** The OSU site uses a more complex technology (ASP.NET WebForms) that requires requests to be made one at a time. Do not change `CONCURRENT_REQUESTS` in the OSU scraper's settings.

---

## Troubleshooting

**"0 rows" in the output**
- Make sure you're using a valid numeric term code (e.g. `1258`, not `"Fall 2025"`).
- Check that you're running the command from inside the `uconn_syllabi_scrapy/` folder.
- Visit https://syllabus.uconn.edu/public/search_term.php to confirm the term exists.

**Download errors for specific files**
- Some files on the site are broken (the server returns an empty file). This is a site issue, not a scraper bug. The metadata row is still saved; only the local filepath will be empty for that row.

**The scraper is slow**
- This is intentional. The scraper waits ~1 second between requests to avoid overloading the university's server. Do not reduce `DOWNLOAD_DELAY` in `settings.py`.

**"No module named scrapy" error**
- Run `pip install -r requirements.txt` from inside the `uconn_syllabi_scrapy/` folder first.

**Output files are in the wrong place**
- The `output/` and `syllabi_downloads/` folders are created in whatever directory you run the `scrapy crawl` command from. Always run from inside `uconn_syllabi_scrapy/`.
