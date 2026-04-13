import argparse
import sys
import zipfile
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "data"
COMMIT_MSG = "Refresh per-institution zip files with latest syllabi"

def _newest_mtime(folder: Path) -> float:
    return max(f.stat().st_mtime for f in folder.rglob("*") if f.is_file())

def build_zips(force: bool = False):
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

        if not force and zip_path.exists():
            zip_mtime = zip_path.stat().st_mtime
            data_mtime = _newest_mtime(subfolder)
            if zip_mtime >= data_mtime:
                size_mb = zip_path.stat().st_size / 1024 / 1024
                print(f"  [{name}] up-to-date, skipping ({size_mb:.1f} MB)")
                zip_paths.append(zip_path)
                continue

        zip_paths.append(zip_path)

        files = sorted(subfolder.iterdir())
        download_files = [f for f in files if f.is_file() and f.suffix != ".csv"]
        csv_files = [f for f in files if f.is_file() and f.suffix == ".csv"]

        print(f"  [{name}]")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for f in download_files:
                arc_path = f"{name}/{name}/{f.name}"
                zf.write(f, arc_path)

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

    for zp in zip_paths:
        run(["git", "add", zp.name])

    old_zip = REPO_DIR / "Data.zip"
    if old_zip.exists():
        run(["git", "rm", "Data.zip"])

    run(["git", "commit", "-m", COMMIT_MSG])
    run(["git", "push", "origin", "main"])
    print("Pushed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package data/ subfolders into zips and push")
    parser.add_argument("--force", action="store_true", help="Rebuild all zips even if up-to-date")
    args = parser.parse_args()
    zips = build_zips(force=args.force)
    git_push(zips)
