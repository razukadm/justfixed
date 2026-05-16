"""Build the JustFixed installer.

Default usage from repo root:
    python build.py

To pin a specific version or expiry:
    python build.py --version 0.1.1 --expiry 2026-08-31

To rebuild without wiping build/ and dist/ (faster, less safe):
    python build.py --no-clean
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import date, timedelta
from pathlib import Path


ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]

BUILD_INFO_PATH = Path("src/justfixed/_build_info.py")
PYPROJECT_PATH  = Path("pyproject.toml")
SPEC_PATH       = Path("justfixed.spec")
ISS_PATH        = Path("installer/justfixed.iss")
VENV_PYINSTALLER = Path(".venv/Scripts/pyinstaller.exe")


def find_iscc() -> Path:
    on_path = shutil.which("iscc") or shutil.which("ISCC")
    if on_path:
        return Path(on_path)
    for candidate in ISCC_CANDIDATES:
        if candidate.exists():
            return candidate
    sys.exit(
        "ISCC.exe not found. Install Inno Setup 6 from "
        "https://jrsoftware.org/isdl.php or add ISCC to PATH."
    )


def read_default_version() -> str:
    if not PYPROJECT_PATH.exists():
        sys.exit(f"pyproject.toml not found at {PYPROJECT_PATH.absolute()}")
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)
    try:
        return data["project"]["version"]
    except KeyError:
        sys.exit("pyproject.toml does not contain [project] version.")


def rewrite_build_info(version: str, today: date, expiry: date) -> None:
    content = BUILD_INFO_PATH.read_text(encoding="utf-8")

    content, n = re.subn(
        r'^VERSION\s*=\s*"[^"]*"',
        f'VERSION     = "{version}"',
        content,
        flags=re.MULTILINE,
    )
    assert n == 1, f"Failed to update VERSION in {BUILD_INFO_PATH}"

    content, n = re.subn(
        r'^BUILD_DATE\s*=\s*date\(\d+,\s*\d+,\s*\d+\)',
        f'BUILD_DATE  = date({today.year}, {today.month}, {today.day})',
        content,
        flags=re.MULTILINE,
    )
    assert n == 1, f"Failed to update BUILD_DATE in {BUILD_INFO_PATH}"

    content, n = re.subn(
        r'^EXPIRY_DATE\s*=\s*date\(\d+,\s*\d+,\s*\d+\)',
        f'EXPIRY_DATE = date({expiry.year}, {expiry.month}, {expiry.day})',
        content,
        flags=re.MULTILINE,
    )
    assert n == 1, f"Failed to update EXPIRY_DATE in {BUILD_INFO_PATH}"

    BUILD_INFO_PATH.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the JustFixed installer.")
    parser.add_argument(
        "--version",
        help="Version string (default: read from pyproject.toml)",
    )
    parser.add_argument(
        "--expiry",
        help="Expiry date YYYY-MM-DD (default: today + 15 days)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip wiping build/ and dist/ before building",
    )
    return parser.parse_args()


def main() -> None:
    start = time.monotonic()

    args = parse_args()

    today  = date.today()
    expiry = date.fromisoformat(args.expiry) if args.expiry else today + timedelta(days=15)
    version = args.version if args.version else read_default_version()

    print(f"Building JustFixed v{version} with expiry {expiry.isoformat()}")
    if not args.version:
        print("Reading version from pyproject.toml")

    # --- Rewrite _build_info.py ---
    print(f"\nRewriting {BUILD_INFO_PATH} ...")
    rewrite_build_info(version, today, expiry)
    print("  Done.")

    # --- Clean ---
    if not args.no_clean:
        for d in ("build", "dist"):
            if Path(d).exists():
                print(f"Removing {d}/")
                shutil.rmtree(d)
    else:
        print("--no-clean: skipping build/ and dist/ removal")

    # --- PyInstaller ---
    if not VENV_PYINSTALLER.exists():
        sys.exit("PyInstaller not found in .venv. Run `pip install pyinstaller` first.")
    print(f"\nRunning PyInstaller ...")
    subprocess.run(
        [str(VENV_PYINSTALLER), "--noconfirm", str(SPEC_PATH)],
        check=True,
    )

    # --- ISCC ---
    iscc = find_iscc()
    print(f"\nRunning ISCC ({iscc}) ...")
    subprocess.run(
        [str(iscc), f"/DAppVersion={version}", str(ISS_PATH)],
        check=True,
    )

    # --- Verify and report ---
    installer_path = Path("dist") / f"JustFixed-Setup-{version}.exe"
    if not installer_path.exists():
        sys.exit(f"Build appeared to succeed but installer not found at {installer_path}")

    elapsed = time.monotonic() - start
    print(f"\nInstaller built: {installer_path.absolute()}")
    print(f"Total time: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
