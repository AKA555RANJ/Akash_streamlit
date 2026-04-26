"""
Full QC for BNC Virtual CSVs — covers every item in bnc_textbook_scraper.md checklist.
Usage: python3 qc_bnc.py <path_to_csv> [--live]
       --live  also fetches live site to compare term/course counts
"""
import csv, re, sys, os, unicodedata, time

# ── helpers ──────────────────────────────────────────────────────────────────

MOJIBAKE_RE = re.compile(r'[ÃÂ][^\s]')   # latin-1 misread as UTF-8 signal chars

def has_mojibake(s):
    return bool(MOJIBAKE_RE.search(s))

def has_accented(s):
    # Any non-ASCII character that isn't a known-OK symbol
    return any(ord(c) > 127 for c in s)

def fvcusno_from_csv(rows):
    url = rows[0].get('source_url', '') if rows else ''
    m = re.search(r'FVCUSNO=(\d+)', url)
    return m.group(1) if m else None

# ── main QC ──────────────────────────────────────────────────────────────────

def qc(path, live=False):
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"[!] Empty CSV: {path}")
        return

    issues   = []
    warnings = []
    school   = os.path.basename(path).replace('_bks.csv','')

    # ── 1. ENCODING ──────────────────────────────────────────────────────────
    for i, r in enumerate(rows):
        for k, v in r.items():
            if '\x1a' in v:
                issues.append(f"[ENC] ROW {i} \\x1a in {k}: {repr(v[:60])}")
            if '\xa0' in v:
                issues.append(f"[ENC] ROW {i} \\xa0 in {k}: {repr(v[:60])}")
            if '\u200b' in v:
                issues.append(f"[ENC] ROW {i} \\u200b in {k}: {repr(v[:60])}")
            if '\u2019' in v or '\u201c' in v or '\u201d' in v:
                issues.append(f"[ENC] ROW {i} curly quote in {k}: {repr(v[:60])}")
            if k in ('title','author','course_title') and has_mojibake(v):
                issues.append(f"[MOJI] ROW {i} mojibake in {k}: {repr(v[:60])}")
            if k in ('title','author','course_title') and has_accented(v):
                warnings.append(f"[ACCENT] ROW {i} accented char in {k}: {repr(v[:60])}")

    # ── 2. STALE / BAD DATA ──────────────────────────────────────────────────
    for i, r in enumerate(rows):
        t = r.get('term','')
        if t and '2026' not in t and not any(s in t for s in ('Spring','Summer','Fall','Winter')):
            issues.append(f"[STALE] ROW {i} term={t!r}")

    for i, r in enumerate(rows):
        if r.get('course_code','') == '*':
            issues.append(f"[SUPPLY] ROW {i} course_code=* title={r.get('title','')[:40]}")

    for i, r in enumerate(rows):
        if not r.get('department_code','').strip():
            issues.append(f"[DEPT] ROW {i} empty dept_code: cc={r.get('course_code','')} title={r.get('course_title','')[:40]}")

    for i, r in enumerate(rows):
        if r.get('author','').strip() in ['.','..','...']:
            issues.append(f"[AUTHOR] ROW {i} dot-only author dept={r.get('department_code','')} cc={r.get('course_code','')}")

    for i, r in enumerate(rows):
        if re.search(r'\bNo\s*Text\b|\bno textbook\b', r.get('title',''), re.I):
            issues.append(f"[NOTEXT] ROW {i} placeholder title: {r.get('title','')[:50]}")

    # ── 3. course_title CONTAMINATION ────────────────────────────────────────
    for i, r in enumerate(rows):
        ct  = r.get('course_title','').strip()
        sec = r.get('section','').strip()
        cc  = r.get('course_code','').strip().lstrip('|')
        if not ct: continue
        tokens = ct.split()
        first  = tokens[0]

        # Skip section checks for rows with no course_code (uniform/supply items)
        if cc:
            # Single-letter section (A, B, O)
            if not sec and re.match(r'^[A-Z]$', first) and len(tokens) > 1:
                issues.append(f"[SEC-1L] ROW {i} single-letter section? dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

            # Pure-uppercase 2–4 char (CHS, HJ, OQ, SQS, VHS — CCC style)
            elif not sec and re.match(r'^[A-Z]{2,4}$', first) and len(tokens) > 1:
                warnings.append(f"[SEC-UP] ROW {i} pure-upper section? dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

            # Alphanumeric (01L, HY01, 2CA, L01)
            elif not sec and re.match(r'^[A-Z]{0,2}\d{1,2}[A-Za-z]*$', first) and re.search(r'\d', first) and len(tokens) > 1:
                issues.append(f"[SEC-AN] ROW {i} alphanum section? dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

            # Decimal section (01.7, 30.9)
            elif not sec and re.match(r'^\d{2}\.\d', first):
                issues.append(f"[SEC-DEC] ROW {i} decimal section? dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

            # SEC prefix
            elif re.match(r'^SEC\s+\S', ct) and not sec:
                issues.append(f"[SEC-PFX] ROW {i} SEC prefix: {ct[:50]}")

        # Digit-start only flagged when section is empty (rows with section already are fine)
        if ct and ct[0].isdigit() and not sec:
            issues.append(f"[DIGT] ROW {i} digit-start title dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

    # Hyphenated course-section in title: "321-01 MANAGEMENT" with empty/pipe course_code
    for i, r in enumerate(rows):
        ct = r.get('course_title','').strip()
        cc = r.get('course_code','').lstrip('|')
        if ct and not r.get('section','').strip():
            m = re.match(r'^(\d+)--?(\d{2,})\s+(.+)$', ct)
            if m:
                issues.append(f"[CC-HYP] ROW {i} hyphen course-section in title dept={r['department_code']} cc={r['course_code']} title={ct[:50]}")

    # ── 4. course_code ISSUES ────────────────────────────────────────────────
    # (informational — these are parser-level; flag unusual patterns)
    for i, r in enumerate(rows):
        cc = r.get('course_code','').lstrip('|')
        if re.match(r'^\d+--\d+', cc):
            warnings.append(f"[CC-DHYP] ROW {i} double-hyphen course_code={r['course_code']}")

    # ── 5. course_title CONTENT ──────────────────────────────────────────────
    for i, r in enumerate(rows):
        ct = r.get('course_title','').strip()
        if ct.endswith('*'):
            issues.append(f"[TRAIL*] ROW {i} trailing * in course_title: {ct[:50]}")
        if re.search(r'_{3,}', ct):
            issues.append(f"[UNDER] ROW {i} underscores in course_title: {ct[:50]}")

    for i, r in enumerate(rows):
        t = r.get('title','').strip()
        if re.search(r'_{3,}', t):
            issues.append(f"[UNDER] ROW {i} underscores in title: {t[:50]}")

    # ── 6. author ISSUES ─────────────────────────────────────────────────────
    for i, r in enumerate(rows):
        auth = r.get('author','')
        if has_mojibake(auth):
            issues.append(f"[MOJI-A] ROW {i} mojibake in author: {repr(auth[:50])}")
        if has_accented(auth):
            warnings.append(f"[ACCENT-A] ROW {i} accented author: {repr(auth[:50])}")

    isbn_rows  = [r for r in rows if r.get('isbn','')]
    empty_auth = [r for r in isbn_rows if not r.get('author','').strip()]
    if isbn_rows:
        pct = 100 * len(empty_auth) / len(isbn_rows)
        if pct > 50:
            issues.append(f"[AUTHOR-EMPTY] {pct:.0f}% of ISBN rows have no author ({len(empty_auth)}/{len(isbn_rows)})")

    # ── 7. source_url / school_id ────────────────────────────────────────────
    fvcusno = fvcusno_from_csv(rows)
    if fvcusno:
        bad_url = [r for r in rows if f'FVCUSNO={fvcusno}' not in r.get('source_url','')]
        if bad_url:
            issues.append(f"[URL] {len(bad_url)} rows have wrong FVCUSNO in source_url")
    else:
        issues.append("[URL] Cannot extract FVCUSNO from source_url")

    sids = set(r.get('school_id','') for r in rows)
    if len(sids) > 1:
        issues.append(f"[SCHOOL_ID] Multiple school_ids: {sids}")

    # ── 8. failed_batches.log ────────────────────────────────────────────────
    log_path = path.replace('.csv','__failed_batches.log')
    http_fails = 0
    missing_enc = 0
    if os.path.exists(log_path):
        with open(log_path) as f:
            for row in csv.DictReader(f, delimiter='\t'):
                if row.get('reason','').startswith('HTTP_'): http_fails += 1
                if row.get('reason','') == 'MISSING_COURSE_ENC': missing_enc += 1
        if http_fails:   issues.append(f"[FAILLOG] {http_fails} HTTP errors in failed_batches.log")
        if missing_enc:  warnings.append(f"[FAILLOG] {missing_enc} MISSING_COURSE_ENC in log")
    else:
        warnings.append("[FAILLOG] No failed_batches.log found")

    # ── 9. LIVE SITE COMPARISON ──────────────────────────────────────────────
    live_summary = []
    if live and fvcusno:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from bnc_textbook_scraper import init_session, fetch_courses
            from curl_cffi.requests import Session

            session = Session(impersonate="chrome")
            info    = init_session(session, fvcusno=int(fvcusno))
            live_terms = {tname: tid for tid, tname in info['terms']}
            live_depts = info['depts']

            csv_terms = set(r.get('term','') for r in rows)

            # Terms on live but missing from CSV
            for tname in live_terms:
                normalized = tname.title() if tname.isupper() else tname
                if tname not in csv_terms and normalized not in csv_terms:
                    issues.append(f"[LIVE] Term {tname!r} on live site but NOT in CSV")

            # Terms in CSV but gone from live
            for ct in csv_terms:
                if ct and ct not in live_terms and ct.upper() not in live_terms:
                    warnings.append(f"[LIVE] Term {ct!r} in CSV but not on live site (may be expired)")

            # Course count comparison per term/dept
            csv_courses = set()
            for r in rows:
                cc = r.get('course_code','').lstrip('|')
                dept = r.get('department_code','')
                term = r.get('term','')
                if cc and dept and term:
                    csv_courses.add((term, dept, cc))

            # Build live unique (term, dept, course_code) — dedup same as CSV does
            from bnc_textbook_scraper import parse_course_desc, clean_term
            live_unique = set()
            for tid, tname in info['terms']:
                for dept_id, dept_name, dept_enckey in live_depts:
                    time.sleep(0.3)
                    courses = fetch_courses(session, info['csid'], int(fvcusno), tid, dept_id, dept_enckey, 0.3)
                    for c in courses:
                        dc, cc, _, _ = parse_course_desc(c.get('COURSE_DESC',''), dept_name)
                        if cc:
                            live_unique.add((clean_term(tname), dc, cc.lstrip('|')))

            csv_unique = set(
                (r.get('term',''), r.get('department_code',''), r.get('course_code','').lstrip('|'))
                for r in rows if r.get('course_code','').strip().lstrip('|')
            )
            live_summary.append(f"Live unique courses: {len(live_unique)} | CSV unique courses: {len(csv_unique)}")

            # Courses on live that are absent from CSV
            missing_from_csv = live_unique - csv_unique
            if missing_from_csv:
                issues.append(f"[LIVE] {len(missing_from_csv)} courses on live site missing from CSV")
                for t, d, c in sorted(missing_from_csv)[:10]:
                    issues.append(f"  → term={t} dept={d} cc={c}")

        except Exception as e:
            warnings.append(f"[LIVE] Could not fetch live site: {e}")

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    terms = {}
    for r in rows: terms[r.get('term','')] = terms.get(r.get('term',''),0)+1

    print(f"\n{'='*60}")
    print(f"  {school}")
    print(f"{'='*60}")
    print(f"  Rows        : {len(rows)}")
    print(f"  Terms       : {dict(sorted(terms.items()))}")
    print(f"  school_id   : {sids}")
    print(f"  FVCUSNO     : {fvcusno}")
    print(f"  ISBN rows   : {len(isbn_rows)}/{len(rows)}")
    print(f"  With section: {len([r for r in rows if r.get('section','').strip()])}")
    if live_summary:
        for s in live_summary: print(f"  {s}")
    if issues:
        print(f"\n  ISSUES [{len(issues)}] — must fix before commit:")
        for iss in issues[:30]: print(f"    ✗ {iss}")
        if len(issues) > 30: print(f"    ... and {len(issues)-30} more")
    else:
        print(f"\n  ✓ No blocking issues")
    if warnings:
        print(f"\n  WARNINGS [{len(warnings)}] — review but may be OK:")
        for w in warnings[:15]: print(f"    ~ {w}")
        if len(warnings) > 15: print(f"    ... and {len(warnings)-15} more")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('path', help='Path to CSV')
    p.add_argument('--live', action='store_true', help='Compare against live site')
    args = p.parse_args()
    qc(args.path, live=args.live)
