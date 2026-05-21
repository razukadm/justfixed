# JustFixed — Dev Routine

Day-to-day operational guide. Three independent procedures: updating the
yield curves, building an expiry-dated installer, and running the app in
dev mode.

For the full build reference (spec internals, installer, debugging a failed
build), see [`BUILD.md`](BUILD.md). This document covers only the everyday
commands.

All commands run from the repo root, `C:\Projects\JustFixed`, in PowerShell.

---

## 1. Updating the curves

Refreshes `curves/latest.json` in the `justfixed-data` repo with the latest
CDI and IPCA data. All installed apps fetch this file on next launch, so this
publishes to every user — review before pushing.

Run this on each B3 trading day you want to publish.

### 1a. Download the two input files

Both files must be for the **same trading day**. Save them into
`C:\Projects\justfixed-data\`.

- **B3 BDI (CDI source)** — the daily market bulletin PDF, `BDI_00_YYYYMMDD.pdf`.
  Download from B3's market-data bulletin page.

  https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/boletim-diario/boletim-diario-do-mercado/

- **ANBIMA ETTJ (IPCA + prefixed source)** — the zero-curve CSV (saved as
  `CurvaZero_.csv`). Download from ANBIMA's ETTJ page.

  https://www.anbima.com.br/informacoes/est-termo/CZ.asp

> **Same-day check.** The ANBIMA CSV carries its reference date near the top
> (the `Parametros` block). Confirm it matches the date in the BDI filename.
> Publishing a CSV from one day with a BDI from another produces a curve file
> whose CDI and IPCA sections silently disagree.

### 1b. Generate and commit the curve file

Replace the date in both places with the trading day you are publishing.

```powershell
cd C:\Projects\JustFixed
.\.venv\Scripts\python.exe tools\publish_curves.py `
  --anbima C:\Projects\justfixed-data\CurvaZero_.csv `
  --b3 C:\Projects\justfixed-data\BDI.pdf `
  --data-repo C:\Projects\justfixed-data `
  --as-of 2026-05-20 --commit
```

`--as-of` is the trading day, which becomes the curve's anchor date. `--commit`
commits `curves/latest.json` to the `justfixed-data` repo but does **not** push.

Expected output ends with a line count and `Committed.` If it prints
`no DI1 settlement rows found`, the BDI file is wrong or corrupt — recheck the
download.

### 1c. Review before publishing

```powershell
git -C C:\Projects\justfixed-data show --stat HEAD
git -C C:\Projects\justfixed-data show HEAD:curves/latest.json | `
  .\.venv\Scripts\python.exe -c "import sys,json; d=json.load(sys.stdin); print('as_of', d['as_of']); print('cdi', len(d['cdi']['vertices']), 'pre', len(d['pre']['vertices']), 'ipca_real', len(d['ipca_real']['vertices']))"
```

Confirm before continuing:

- `show --stat` lists **only** `curves/latest.json` — nothing else.
- `as_of` matches the trading day you published.
- `cdi` has roughly 45–48 vertices; `pre` and `ipca_real` have 7 each.

If anything looks off, stop and investigate — do not push.

### 1d. Push

```powershell
git -C C:\Projects\justfixed-data push
git -C C:\Projects\justfixed-data status -sb
```

`status -sb` should show `main...origin/main` with no "ahead" — local and
remote now match. The curve is live; users get it on next app launch.

---

## 2. Building an installer with an expiry date

Produces `dist\JustFixed-Setup-{version}.exe` — the file beta testers download.
The app refuses to launch after the expiry date.

```powershell
cd C:\Projects\JustFixed
.\.venv\Scripts\python.exe build.py --expiry 2026-08-15
```

Replace `2026-08-15` with the date the beta build should stop working
(`YYYY-MM-DD`). Without `--expiry`, the default is today + 15 days.

The build takes about 2 minutes and prints the final installer path on success.

Other flags (`--version`, `--no-clean`) and full details are in
[`BUILD.md`](BUILD.md).

> **Note.** `build.py` rewrites `src/justfixed/_build_info.py` every run. This
> is expected. Leave it uncommitted for routine beta builds; commit it only
> when a build is an intentional release snapshot. See `BUILD.md` for the
> reasoning.

---

## 3. Running the app in dev mode

Launches the installed app with the dev environment variable set.

```powershell
$env:JUSTFIXED_DEV = "1"
& "$env:LOCALAPPDATA\Programs\JustFixed\JustFixed.exe"
```

The `$env:JUSTFIXED_DEV` setting applies only to the current PowerShell
window. Open a new window, or close this one, to launch normally again.

<!-- FILL IN: one line on what dev mode actually changes (e.g. uses the dev
database instead of the user's real data / enables verbose logging / bypasses
the expiry check) and how to confirm it is active. -->

---

*Keep this file updated as the routine changes. It lives in the repo so edits
are version-controlled alongside the code.*
