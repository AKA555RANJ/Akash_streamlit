#!/usr/bin/env python3
"""
package_data.py — Build per-institution zip files and push to GitHub via Git LFS.

For each subfolder in data/, creates a zip like:
  bergen_community_college__3061268__syllabus.zip
  └── bergen_community_college__3061268__syllabus/
      ├── bergen_community_college__3061268__syllabus/   ← scraped files (PDFs, HTMLs, etc.)
      │   ├── ACC-107.pdf
      │   └── ...
      └── bergen_community_college__3061268__syllabus.csv ← metadata

Rules:
  - data/ (lowercase) is the source folder
  - One zip per subfolder, placed at the repo root
  - CSV metadata sits at the top level inside the zip (beside the files folder)
  - Non-CSV files go into a nested subfolder with the same name
"""

import sys
import zipfile
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "data"
COMMIT_MSG = "Refresh per-institution zip files with latest syllabi"


def build_zips():
    if not DATA_DIR.exists():
        fallback = REPO_DIR / "Data"
        if fallback.exists():
            print(f"[warn] 'data/' not found, using '{fallback}' — rename it to 'data/' for consistency")
            source = fallback
        else:
            print("[error] No 'data/' folder found. Aborting.")
            sys.exit(1)
    else:
        source = DATA_DIR

    subfolders = sorted(p for p in source.iterdir() if p.is_dir())
    if not subfolders:
        print("[error] No subfolders found inside data/. Aborting.")
        sys.exit(1)

    print(f"Source : {source}")
    print(f"Subfolders to package: {[s.name for s in subfolders]}\n")

    zip_paths = []

    for subfolder in subfolders:
        name = subfolder.name
        zip_path = REPO_DIR / f"{name}.zip"
        zip_paths.append(zip_path)

        files = sorted(subfolder.iterdir())
        download_files = [f for f in files if f.is_file() and f.suffix != ".csv"]
        csv_files = [f for f in files if f.is_file() and f.suffix == ".csv"]

        print(f"  [{name}]")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            # Scraped files go into name/name/
            for f in download_files:
                arc_path = f"{name}/{name}/{f.name}"
                zf.write(f, arc_path)

            # CSV metadata goes into name/
            for f in csv_files:
                arc_path = f"{name}/{f.name}"
                zf.write(f, arc_path)

            print(f"    downloads : {len(download_files)} files")
            print(f"    metadata  : {len(csv_files)} CSV(s)")

        size_mb = zip_path.stat().st_size / 1024 / 1024
        print(f"    output    : {zip_path.name} ({size_mb:.1f} MB)\n")

    return zip_paths


def git_push(zip_paths):
    print("\n--- Git ---")

    def run(cmd):
        result = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        if result.returncode != 0:
            print(f"[error] Command failed: {' '.join(cmd)}")
            sys.exit(result.returncode)

    # Track new zip files with LFS and stage them
    for zp in zip_paths:
        run(["git", "add", zp.name])

    # Remove old Data.zip if it exists and is tracked
    old_zip = REPO_DIR / "Data.zip"
    if old_zip.exists():
        run(["git", "rm", "Data.zip"])

    run(["git", "commit", "-m", COMMIT_MSG])
    run(["git", "push", "origin", "main"])
    print("Pushed successfully.")


if __name__ == "__main__":
    zips = build_zips()
    git_push(zips)
