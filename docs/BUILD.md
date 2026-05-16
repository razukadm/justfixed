# Building JustFixed

This document covers manual and diagnostic builds. The everyday build tool is
`build.py` (Pass 5, not yet written); this doc is for understanding the spec
directly and for debugging when the automated build fails.

---

## Prerequisites

- **Python venv** at repo root (`.venv\`). Standard project setup — see
  `docs/README.md`.
- **PyInstaller** installed in that venv:

      .\.venv\Scripts\pip install pyinstaller

  This is a build-time dependency only. Do not add it to `pyproject.toml`
  dependencies — it has no business being installed in end-user environments.

---

## Building the bundle

From repo root, one-shot build:

    .\.venv\Scripts\pyinstaller justfixed.spec

Subsequent rebuilds (skip the "output directory not empty" prompt):

    .\.venv\Scripts\pyinstaller --noconfirm justfixed.spec

Output lands in `dist\JustFixed\`. The `.exe` is `dist\JustFixed\JustFixed.exe`.
The whole `dist\JustFixed\` directory is the distribution unit — the exe alone
won't run without the `_internal\` sibling directory.

Build time: ~60–90 seconds on this machine.

---

## What's in the spec

| Choice | Why |
|---|---|
| One-folder mode (not `--onefile`) | Faster start, fewer AV false positives |
| `pathex=['src']` | Handles the src-layout package structure |
| `console=False` | GUI app — no spurious black console window alongside the main window |
| `datas=collect_data_files('bizdays', includes=['*.cal'])` | `bizdays` locates its calendar data via `__file__` at runtime; PyInstaller doesn't auto-include `.cal` files. Without this line the app launches but "Project as of today" fails with `Invalid calendar: ANBIMA` |
| `excludes=['tkinter', 'PyQt5', 'PyQt6', 'pytest']` | Reduces bundle size; none are used |
| `icon='assets/icon.ico'` | Placeholder — see `assets/README.md` |
| `version='version_info.txt'` | Embeds Windows file metadata (version, description, copyright) in the exe |

---

## Build-time expiry

`src/justfixed/_build_info.py` holds `VERSION`, `BUILD_DATE`, and `EXPIRY_DATE`
as module-level constants. The app refuses to launch after `EXPIRY_DATE`.

The committed values reflect the most recent build. To change them by hand:
edit `_build_info.py`, rebuild. `build.py` (Pass 5) will do this
programmatically via `--expiry` and `--version` arguments.

---

## Known gotchas

**Windows shell icon cache.** After rebuilding, Explorer often shows the
previous icon for `JustFixed.exe` even though the rebuild embedded a different
icon resource. Verify by renaming the bundle folder — the renamed copy shows the
actual embedded icon. End users won't encounter this because the installer
(Pass 4) writes to a different path.

**Build cache vs. fresh build.** PyInstaller's `build\` directory caches
intermediate artifacts. `--noconfirm` clears `dist\` but not `build\`. If a
rebuild produces unexpected output (e.g., wrong icon, stale module), wipe both
directories and rebuild from scratch:

    Remove-Item -Recurse -Force build, dist
    .\.venv\Scripts\pyinstaller justfixed.spec

`build.py` (Pass 5) wipes `build\` automatically before every run.

**The four harmless warnings.** Every build emits these:

    WARNING: Hidden import "jinja2" not found!
    WARNING: Hidden import "pysqlite2" not found!
    WARNING: Hidden import "MySQLdb" not found!
    WARNING: Hidden import "psycopg2" not found!

These are optional SQLAlchemy and pandas dialect drivers that JustFixed doesn't
use. They don't affect the bundle and are safe to ignore.

---

## Manual smoke check

1. Double-click `dist\JustFixed\JustFixed.exe` from Explorer (not from a
   terminal — Explorer is how end users launch, and it's the path that
   surfaces Qt plugin issues).
2. Verify:
   - Main window appears and the table renders with dev-database data.
   - Help → About shows correct version, build date, and expiry.
   - "Project as of today" runs without errors and populates Current/Projected
     columns and FGC badges.
3. Run from a terminal to catch any stderr the GUI swallows:

       .\dist\JustFixed\JustFixed.exe
