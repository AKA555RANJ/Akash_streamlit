#!/usr/bin/env python3
"""
package_data.py — Build Data.zip and push to GitHub via Git LFS.

Zip structure (subfolders directly at root, metadata separated):
  bergen_community_college__3061268__syllabus/
    ACC-107.pdf
    ...
  delaware_technical_community_college_terry__2984303__syllabus/
    ACC-101.html
    ...
  metadata/
    bergen_community_college__3061268__syllabus.csv
    delaware_technical_community_college_terry__2984303__syllabus.csv

Rules:
  - data/ (lowercase) is the source folder
  - Only the subfolders inside data/ are compressed, NOT the parent data/ folder
  - CSV metadata files go into metadata/ at the zip root, not inside download subfolders
"""

import sys
import zipfile
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "data"
ZIP_PATH = REPO_DIR / "Data.zip"
COMMIT_MSG = "Refresh Data.zip with latest syllabi"


def build_zip():
    if not DATA_DIR.exists():
        # Fall back to capital-D Data/ if data/ doesn't exist yet
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
    print(f"Output : {ZIP_PATH}")
    print(f"Subfolders to package: {[s.name for s in subfolders]}\n")

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for subfolder in subfolders:
            files = sorted(subfolder.iterdir())
            download_files = [f for f in files if f.suffix != ".csv"]
            csv_files = [f for f in files if f.suffix == ".csv"]

            # Add download files directly under the subfolder name (not under data/)
            for f in download_files:
                arc_path = f"{subfolder.name}/{f.name}"
                zf.write(f, arc_path)

            print(f"  [{subfolder.name}]")
            print(f"    downloads : {len(download_files)} files")

            # Add CSVs to a separate metadata/ directory at zip root
            for f in csv_files:
                arc_path = f"metadata/{f.name}"
                zf.write(f, arc_path)
                print(f"    metadata  : metadata/{f.name}")

    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print(f"\nDone: {ZIP_PATH.name} ({size_mb:.1f} MB)")


def git_push():
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

    run(["git", "add", "Data.zip"])
    run(["git", "commit", "-m", COMMIT_MSG])
    run(["git", "push", "origin", "main"])
    print("Pushed successfully.")


if __name__ == "__main__":
    build_zip()
    git_push()
