import csv
import os
import sys
import time
from datetime import datetime

CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "south_texas_college__3094183__bks",
    "south_texas_college__3094183__bks.csv",
)

ALL_DEPTS = [
    "ACCT","ACNT","AGRI","ANTH","ARCE","ARCH","ARTC","ARTS","AUMT",
    "BIOL","BMGT","BUSG","BUSI",
    "CDEC","CETT","CHEF","CHEM","CJSA","CNBT","COMM","COSC","CRIJ","CSME",
    "DEMR","DFTG","DNTA",
    "ECON","EDUC","ELPT","EMSP","ENGL","ENGR","EPCT",
    "FIRT",
    "GEOG","GEOL","GOVT",
    "HAMG","HART","HESI","HIST","HMSY","HRPO","HUMA","HVAC",
    "IMED","INEW","ITSW","ITNW",
    "KINE",
    "LGLA",
    "MATH","MCHN","MRKG","MUAP","MUEN","MUSI",
    "NURA","NURSE",
    "OSHT",
    "PHED","PHIL","PHYS","PLAB","POFI","POFT","PSYC","PTAC",
    "RADR","RNSG",
    "SCIT","SLNG","SOCW","SOCI","SPAN","SPCH","SRVY",
    "TECM","TECA","TMGT",
    "VNSG",
    "WLDG",
]

def read_csv_stats():
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        return 0, set(), {}
    dept_counts = {}
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            if dept:
                dept_counts[dept] = dept_counts.get(dept, 0) + 1
    total = sum(dept_counts.values())
    return total, set(dept_counts.keys()), dept_counts

def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    prev_rows = 0
    prev_depts = set()
    stall_count = 0
    print(f"[monitor] Watching {CSV_PATH}")
    print(f"[monitor] Checking every {interval}s\n")

    while True:
        total, depts, dept_counts = read_csv_stats()

        now = datetime.now().strftime("%H:%M:%S")
        new_rows = total - prev_rows
        new_depts = depts - prev_depts

        if total > 0 and new_rows == 0:
            stall_count += 1
        else:
            stall_count = 0

        print(f"[{now}] {total} rows | {len(depts)} depts | +{new_rows} rows | +{len(new_depts)} depts", end="")
        if new_depts:
            print(f" NEW: {sorted(new_depts)}", end="")
        print()

        if stall_count >= 3:
            print(f"  ⚠ WARNING: No new rows for {stall_count * interval}s — scraper may be stuck or blocked!")

        if depts:
            sorted_scraped = sorted(depts)
            last_dept = sorted_scraped[-1]
            expected_before = [d for d in ALL_DEPTS if d <= last_dept]
            missing = set(expected_before) - depts
            if missing:
                print(f"  ⚠ MISSING depts (should be before {last_dept}): {sorted(missing)}")

        prev_rows = total
        prev_depts = depts

        time.sleep(interval)

if __name__ == "__main__":
    main()
