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

---

## Building the installer

After the PyInstaller bundle is built (previous section), the Inno Setup
installer wraps `dist/JustFixed/` into a single setup `.exe` that beta
testers download and double-click.

### Prerequisites

- Inno Setup 6 installed. Standard path: `C:\Program Files (x86)\Inno Setup 6\`.
- Download: https://jrsoftware.org/isdl.php (regular installer, not the
  QuickStart Pack).
- The compiler used is `ISCC.exe`. The Inno Setup IDE is not needed.

### Manual compile

From repo root, with `dist/JustFixed/` already built:

    & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\justfixed.iss

To override the version at compile time (used by `build.py`):

    & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\justfixed.iss /DAppVersion=0.1.1

Output: `dist\JustFixed-Setup-{version}.exe` (e.g. `dist\JustFixed-Setup-0.1.0.exe`).

Compile time: ~10–30s. Most of the time is LZMA2 compression of the bundle.

### What the installer does

- **Per-user install** at `%LOCALAPPDATA%\Programs\JustFixed\`. No UAC prompt;
  no admin elevation required.
- **Start Menu shortcut** under JustFixed group, default checked at install time.
- **Desktop shortcut** offered as an unchecked option.
- **Uninstall entry** in Settings → Apps.
- **Compressed** with LZMA2 / solid compression; setup `.exe` is ~70–80% the size
  of the raw `dist/JustFixed/` bundle.

### Critical invariant

The installer never touches `%USERPROFILE%\.justfixed\`. User data lives there
and is the app's responsibility, not the installer's. Verified by the Pass 4a
smoke check: uninstall removes the install dir cleanly while the data dir is
left intact.

If a future change to `installer\justfixed.iss` ever adds a `[Files]` or
`[Dirs]` entry pointing at `{userprofile}\.justfixed\`, that's a critical bug.
Reject any such change.

### Stable AppId

`installer\justfixed.iss` hardcodes a GUID under `[Setup] AppId=`. **This GUID
must never change.** Windows uses it to identify the product across installs —
changing it would make each installed version look like a separate product,
breaking upgrades and leaving orphaned entries in Settings → Apps.

If a regeneration is genuinely needed (e.g. forking the project under a
different name), the new project gets a new GUID.

### Smoke check

Same six steps as Pass 4a; documented here for future reference:

1. Double-click the setup `.exe`. Verify no UAC prompt, default path is
   `%LOCALAPPDATA%\Programs\JustFixed`, install completes.
2. Launch via Start Menu shortcut.
3. End-to-end: window opens, table renders, "Project as of today" works,
   Help → About shows correct version.
4. Confirm `%USERPROFILE%\.justfixed\justfixed.db` is unchanged and the
   installed app uses it.
5. Uninstall via Settings → Apps. Verify install dir is removed; data dir
   survives.
6. Reinstall. Verify clean install and data still intact.

### Automation

`build.py` (next section, when added) chains PyInstaller + ISCC into a single
command. The manual steps above are for debugging the installer layer
specifically, not the everyday build flow.
