# BNC Virtual Textbook Scraper — Context Document

## What This Scraper Does

Scrapes textbook/course material adoption data from any institution hosted on **bncvirtual.com**. Given a URL like `https://bncvirtual.com/bsol` or a FVCUSNO ID, it discovers all terms, departments, and courses, then extracts textbook details (ISBN, title, author, adoption code) into a CSV.

## File Location

`/workspaces/Akash_streamlit/bnc_textbook_scraper.py`

## Usage

```bash
# Short URL (auto-discovers FVCUSNO)
python bnc_textbook_scraper.py --url https://bncvirtual.com/<short_code>

# Direct FVCUSNO
python bnc_textbook_scraper.py --fvcusno <number>

# With IPEDS school ID override
python bnc_textbook_scraper.py --fvcusno <number> --school-id <ipeds_id>

# All options
python bnc_textbook_scraper.py --url <url> --school-id <id> --batch-size 25 --delay 0.5 --output-dir <path>
```

## Output

CSV at `data/bnc_{fvcusno}_textbooks/bnc_{fvcusno}_textbooks.csv`

## CSV Schema

| Field | Mandatory | Notes |
|---|---|---|
| source_url | Yes | chooseCourses URL |
| school_id | Yes | FVCUSNO or `--school-id` override |
| department_code | Yes | Parsed from course code prefix (e.g. "LAW" from "LAW501") |
| course_code | Yes | Numeric/alphanumeric part (e.g. "501"). Kept as text, preserves leading zeros |
| course_title | Optional | Remaining text after code (e.g. "TORTS" from "LAW501 TORTS") |
| section | Optional | Empty — BNC site doesn't expose section info |
| section_instructor | Optional | Empty — BNC site doesn't expose instructor info |
| term | Optional | e.g. "Spring 2026" |
| isbn | Optional | Normalized: hyphens removed, anti-scrape bogus spans stripped |
| title | Optional | Textbook title |
| author | Optional | Author(s) |
| material_adoption_code | Optional | Raw value (e.g. "Required", "REQUIRED, PREVIOUS PURCHASE POSSIBLE") |
| crawled_on | Yes | ISO 8601 UTC timestamp |

## How the Site Works (BNC Virtual Architecture)

### Key Concepts
- **FVCUSNO**: Institution ID. Each school on bncvirtual.com has a unique numeric FVCUSNO.
- **CSID**: Session ID. Extracted from JavaScript on first page load. Required for all subsequent requests.
- **Encrypted keys**: Department keys and course keys are encrypted server-side. Must use as-is from responses.
- **Cloudflare**: Site is behind Cloudflare — requires `curl_cffi` with Chrome impersonation.

### Three-Step Request Flow

**Step 1 — GET chooseCourses page**
```
GET https://bncvirtual.com/vb_buy2.php?FVCUSNO={id}&ACTION=chooseCourses
```
Extracts from inline `<script>` tags:
- `var CSID = '...'` — session ID
- `selectTerm(...)` calls → term IDs + names (e.g. `'70108', 'Spring 2026'`)
- `selectDept(...)` calls → dept IDs + names + encrypted keys (e.g. `'2173021', 'Birmingham School of Law', 'DXWu7VMfrq8OTV6AZKD0'`)

**Step 2 — POST to get course list (per term/dept)**
```
POST https://bncvirtual.com/vb_crs_srch.php?CSID={csid}&FVCUSNO={id}
Body: FvTerm={term_id}&FvDept={encrypted_dept_key}&R=1
```
Returns JSON:
```json
{
  "success": {
    "<dept_id>": [
      {
        "COURSE": "32758525",
        "COURSE_DESC": "LAW501 TORTS",
        "DATE_DESC": "01/03/2026 - 04/18/2026",
        "COURSE_ENC": "n3KWKD1gW2anSnBBUENXpA--"
      }
    ]
  }
}
```
Note: `dept_courses` can be a **list** (not always a dict with index keys).

**Step 3 — POST to get textbook adoptions (batched, up to 25 courses)**
```
POST https://bncvirtual.com/vb_buy2.php?ACTION=chooseAdoptions&CSID={csid}&FVCUSNO={id}&VCHI=1
Body: fvCourseKeyList={enc_key1},{enc_key2},...
```
Returns full HTML page with textbook details.

### Adoption Page HTML Structure

```
<form id="BookMaterialBuy">
  <!-- Per-course block (repeats): -->
  <input name="supsort_d_desc_1" value="Spring 2026 |div| Birmingham School of Law">
  <input name="supsort_c_desc_1" value="LAW501 TORTS |div| 01/03/2026 - 04/18/2026">
  <div class="cmCourseHeader">...</div>
  <div class="collapse in crs_adpts_collapse">
    <!-- Per-textbook (repeats): -->
    <p class="red text-uppercase">Required</p>
    <h2 class="p0m0 h3">Book Title <span class="nobold small">Edition info</span></h2>
    <table class="cmTableBkInfo">
      <tr><td>Author: </td><td>Author Name</td></tr>
      <tr><td>ISBN-13: </td><td>979-8<span style="display: none;">bogus</span>8-920922-9-6</td></tr>
      <tr><td>ISBN-10: </td><td><span style="display: none;">bogus</span></td></tr>
      <tr><td>Edition/Copyright: </td><td>15TH 24</td></tr>
      <tr><td>Publisher: </td><td>West Academic</td></tr>
    </table>
  </div>
  <br>
  <!-- Next course block... -->
</form>
```

### ISBN Anti-Scraping

BNC injects `<span style="display: none;">bogus</span>` inside ISBN table cells. The scraper strips these hidden spans before extracting the ISBN text, then removes hyphens.

## Dependencies

All in `requirements_scraper.txt`:
- `curl_cffi` — Cloudflare bypass (Chrome TLS fingerprint)
- `beautifulsoup4` + `lxml` — HTML parsing
- `tqdm` — progress bar

## Known Limitations

- **No section/instructor data**: BNC Virtual does not expose section identifiers or instructor names in the adoption flow. These fields are always empty.
- **Single session**: CSID is session-bound. The scraper uses one `curl_cffi` session throughout — don't parallelize requests.
- **Batch limit**: Max 25 courses per chooseAdoptions POST (matches site's `alloted_crs_rows` JS variable).

## Tested Institutions

| Short URL | FVCUSNO | Institution | Courses | Result |
|---|---|---|---|---|
| `/bsol` | 11414 | Birmingham School of Law | 19 | 29 textbook rows, 23 unique ISBNs |

## Adding a New Institution

Just run with the new URL or FVCUSNO:
```bash
python bnc_textbook_scraper.py --url https://bncvirtual.com/<new_short_code>
```
No code changes needed. The scraper auto-discovers terms, departments, and courses for any BNC Virtual institution.

---

## Post-Scrape QC Checklist

**Automated tool:** `python3 qc_bnc.py <path_to_csv> [--live]`
- Runs all checks below automatically and reports issues/warnings
- `--live` flag fetches live site and compares course counts (run this for thorough QC)
- File: `qc_bnc.py` in repo root

Run these checks on every BNC Virtual CSV before committing. Fix any failures before pushing.

### 1. Encoding Issues
- [ ] **`\x1a` control char** — garbled apostrophe from source HTML. Replace with `'`
- [ ] **`\xa0` non-breaking space** — replace with regular space
- [ ] **`\u200b` zero-width space** — invisible char in `course_title` or `title`. Strip
- [ ] **Curly/smart quotes** — `\u2019` (`'`), `\u201c`/`\u201d` (`""`). Replace with plain ASCII
- [ ] **Mojibake** — UTF-8 bytes misread as latin-1 (e.g. `AnzaldÃºa` → `Anzaldúa`). Fix: `.encode('latin-1').decode('utf-8')`
- [ ] **Accented/special chars** — `é`, `á`, `ö`, `®` etc. Normalize: `unicodedata.normalize('NFKD').encode('ascii','ignore')`

> Apply encoding fixes **only to BNC Virtual files** — not ecampus, kubstore, or other platforms.

### 2. Stale / Bad Data Rows
- [ ] **Stale terms** — flag terms containing old years (2015–2025). Non-year-based terms (e.g. `Pinellas Clearwater`, `Online Spring Block AB`) are fine
- [ ] **Supply rows** — `course_code='*'` with `title='SCHOOL SUPPLIES'`. Strip entirely
- [ ] **Empty department rows** — rows where `department_code` is blank. Investigate
- [ ] **Dot-only authors** — author field contains only `.` / `..` / `...`. Clear
- [ ] **No-text placeholder titles** — e.g. `No Text Required`, `No Textbook`. Clear the row

### 3. Parser — `course_title` Field Contamination
Section codes or course codes appearing in `course_title` instead of their proper fields:

- [ ] **Single-letter section** — e.g. `A`, `B`, `T` at start. Extract to `section` (e.g. `T CAPSTONE` → section=`T`, title=`CAPSTONE`)
- [ ] **Alphanumeric section** — e.g. `01L`, `SH1`, `OL1`, `FT1`, `L1`, `PS2`, `1T2`, `5W1` at start. Extract to `section`
- [ ] **Term-track codes** — e.g. `1T2`, `2T2`, `3T2` (Trinity Washington style). Extract to `section`
- [ ] **Pure-uppercase 2–4 char** — e.g. `CHS`, `HJ`, `CNL`, `FNP` at start. May be section code — review context
- [ ] **Decimal section** — e.g. `01.7`, `30.9` at start. Extract to `section`
- [ ] **Hyphenated course-section** — e.g. `321-01 MANAGEMENT` (requires 2+ digit course number). Split into `course_code`/`section`
- [ ] **Course code with colon** — e.g. `495: FILM & CJ SPECIAL TOP` where `course_code` is empty. Extract digits before `:` as `course_code`
- [ ] **Multi-course-code prefix** — e.g. `420,440,450 CLINICAL PATHOLOGY` where `course_code` is empty. Extract comma-list as `course_code`
- [ ] **Grade-range prefix** — e.g. `5-12 RDG/WRTG ASSESSMENT`. These are legitimate K-12 titles — do NOT extract as section
- [ ] **Mixed course/section in empty cc row** — e.g. `MSN/DNP PROG PROGRAM REQUIRED TEXTS`. Parse by known school pattern

### 4. Parser — `course_code` Field Issues
- [ ] **Hyphenated course codes** — `101-1`, `125-1`. Keep as-is; do NOT split single-digit suffix
- [ ] **Double-hyphen** — `542--91`. Treat same as single hyphen
- [ ] **Decimal course codes** — `548.40`, `420.S1`, `542.N3`. Parser allows `.` in course code token
- [ ] **Asterisk-delimited format** — `BUSN*504*OLS` style. Parser handles `*` as delimiter

### 5. `course_title` Content Issues
- [ ] **Trailing `*`** — e.g. `FIELD BIOLOGY*`. Strip with `rstrip('*')`
- [ ] **Underscore placeholders** — `Elementary _______ I`. Strip from `course_title` and `title`

### 6. `author` Field Issues
- [ ] **Accented author names** — `José`, `Klára`, `Renée`, `Barí`. Normalize to ASCII
- [ ] **Mojibake in author** — fix before ASCII normalization
- [ ] **Empty author on rows with ISBN** — acceptable individually; flag if >50% of ISBN rows have blank author

### 7. Duplicate Rows
- [ ] **Timestamp-only duplicates** — rows identical except `crawled_on`/`updated_on`. Remove (happens when same course appears in multiple batches). Dedup key: all fields except timestamps
- [ ] **Legitimate near-duplicates** — same course/book with different `material_adoption_code` or slightly different `course_title` abbreviation. Keep both

### 8. Live Site Comparison (`--live` flag)
- [ ] **Run `qc_bnc.py --live`** for every school — compares unique `(term, dept, course_code)` tuples against live site
- [ ] **Missing courses** — if live has courses not in CSV, fetch them individually using `fetch_adoptions` and append
- [ ] **Cross-term batch dedup bug** — BNC server deduplicates enc keys across terms in a single batch, causing some courses to be silently skipped. Fix: fetch missing courses one-at-a-time using their individual `COURSE_ENC`
- [ ] **CSV has more than live** — acceptable (courses may have been dropped from live after scraping)
- [ ] **Non-standard term names** — schools like Pinellas TCC use program names instead of semester names. Live comparison still works; STALE check ignores these

### 9. Multi-Campus / Shared FVCUSNO
- [ ] **Shared store** — check if multiple campuses share one FVCUSNO (e.g. CCC 7 campuses share FVCUSNO=4486). Scrape once, copy CSV with updated `school_id` per campus
- [ ] **`school_id` column** — must match the OPEID of the specific campus, not the scrape FVCUSNO

### 10. Final Spot-Checks Before Commit
- [ ] Row count is non-trivial (large university → thousands of rows expected)
- [ ] `source_url` contains the correct FVCUSNO for all rows
- [ ] `school_id` column is consistent and matches OPEID
- [ ] No stale year (2015–2025) in any term value
- [ ] No `course_code='*'` supply rows remain
- [ ] No `\x1a`, `\u200b`, `\xa0` chars anywhere in the file
- [ ] `department_code` is non-empty for all rows with a valid course
- [ ] `section` field populated where applicable — not stuck in `course_title`
- [ ] `course_title` does not start with an extractable section code or embedded course code
- [ ] `__failed_batches.log` reviewed — zero HTTP errors, zero missing `COURSE_ENC` entries ideally
