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

Run these checks on every BNC Virtual CSV before committing. Fix any failures before pushing.

### 1. Encoding Issues
- [ ] **`\x1a` control char** — garbled apostrophe from source HTML. Replace with `'`
- [ ] **`\xa0` non-breaking space** — replace with regular space
- [ ] **Mojibake** — UTF-8 bytes misread as latin-1 (e.g. `AnzaldÃºa` → `Anzaldúa`). Fix: `.encode('latin-1').decode('utf-8')`
- [ ] **Accented/special chars** — `é`, `á`, `ö`, `®` etc. cause `??` downstream. Normalize: `unicodedata.normalize('NFKD').encode('ascii','ignore')`
- [ ] **Curly/smart quotes** — `\u2019` (`'`), `\u201c`/`\u201d` (`""`). Replace with plain ASCII equivalents
- [ ] **Zero-width space** — `\u200b` invisible char in `course_title` or `title`. Strip

> Apply encoding fixes **only to BNC Virtual files** — not ecampus, kubstore, or other platforms.

### 2. Stale / Bad Data Rows
- [ ] **Stale terms** — keep only current year (2026+) terms; strip Fall 2019, Spring 2020, Summer 2025 etc.
- [ ] **Supply rows** — `course_code='*'` with `title='SCHOOL SUPPLIES'`. Strip entirely
- [ ] **Empty department rows** — rows where `department_code` is blank (parser fallback failure). Investigate
- [ ] **Dot-only authors** — author field contains only `.` or similar placeholder. Clear
- [ ] **No-text placeholder titles** — e.g. `title='405 No Text Required'`. Clear the row

### 3. Parser — `course_title` Field Contamination
These are cases where section codes or course codes appear in `course_title` instead of their proper fields:

- [ ] **Alphanumeric section in title** — e.g. `01L`, `2CA`, `HY01` at start of `course_title`. Should be in `section`
- [ ] **Pure-uppercase section in title** — e.g. `CHS`, `HJ`, `OQ`, `SQS`, `VHS` (CCC/community college style). Should be in `section`
- [ ] **Single-letter section in title** — e.g. `A`, `B`, `O` (Northwestern style). Should be in `section`
- [ ] **Decimal section in title** — e.g. `01.7`, `30.9` at start of `course_title`. Should be in `section`
- [ ] **Hyphenated course-section in title** — e.g. `321-01 PRINCIPLES OF MANAGEMENT`. Split into `course_code=321`, `section=01`
- [ ] **L-prefix lab courses in title** — e.g. `L 111 01 Fundamentals of Biology`. Parse as `course_code=111`, `section=L01`
- [ ] **Digit-leading dept codes in title** — e.g. `432IBEW`. Fallback must use `department_name` for dept

### 4. Parser — `course_code` Field Issues
- [ ] **Hyphenated course codes** — `101-1`, `125-1` (CCC style). Keep as-is; do NOT split single-digit suffix
- [ ] **Double-hyphen** — `542--91`. Treat same as single hyphen; split into `course_code=542`, `section=91`
- [ ] **Decimal course codes** — `548.40`, `542.N3`. Parser must allow `.` in course code token
- [ ] **Asterisk-delimited format** — `BUSN*504*OLS` style. Parser handles `*` as delimiter

### 5. `course_title` Content Issues
- [ ] **Trailing `*`** — e.g. `ASDC 1012 *`. Strip with `rstrip('*')`
- [ ] **Underscore placeholders** — `Elementary _______ I`. Strip underscores from `course_title` and `title` only (not URLs)

### 6. `author` Field Issues
- [ ] **Accented author names** — `José`, `Klára Móricz`. Normalize to ASCII (`Jose`, `Klara Moricz`)
- [ ] **Mojibake in author** — fix before ASCII normalization
- [ ] **Empty author on rows with ISBN** — acceptable individually; flag if >50% of ISBN rows have blank author

### 7. Multi-Campus / Shared FVCUSNO
- [ ] **Shared store** — check if multiple campuses share one FVCUSNO (e.g. CCC 7 campuses share FVCUSNO=4486; WCU campuses share one store). Scrape once, copy CSV with updated `school_id` per campus
- [ ] **`school_id` column** — must match the OPEID of the specific campus, not the scrape FVCUSNO

### 8. Final Spot-Checks Before Commit
- [ ] Row count is non-trivial (large university → thousands of rows expected)
- [ ] `source_url` contains the correct FVCUSNO
- [ ] `school_id` column matches the school's OPEID
- [ ] Only current-year terms present (no pre-2026 terms)
- [ ] No `course_code='*'` supply rows remain
- [ ] No `\x1a`, `\u200b`, `\xa0` chars anywhere in the file
- [ ] `department_code` is non-empty for all rows with a valid course
- [ ] `section` field is populated where applicable — not stuck in `course_title`
- [ ] `course_title` does not start with a digit, single uppercase letter, or decimal number
- [ ] `__failed_batches.log` reviewed — check for HTTP errors or missing `COURSE_ENC` entries
