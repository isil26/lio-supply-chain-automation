# Fresh-machine run (T56)

isil-agent, Sat 21 Nov 2026 ~18:30 CET. A fresh `git clone` into an empty folder on **Windows 11** (Python 3.11.9, no WSL), following README only.

| Step (README) | Result on Windows | Fix |
|---|---|---|
| `python3 -m venv .venv` | `python3` does not exist on Windows (opens the Microsoft Store stub). | README: use `python` (or `py`) on Windows. |
| `source .venv/bin/activate` | Bash only. | README: `.venv\Scripts\Activate.ps1` in PowerShell. |
| `pip install -r requirements.txt` | OK. | — |
| `python -m src.orchestrator --data case-data` | **Crash:** `ModuleNotFoundError: fcntl` (`src/docs/pipeline.py`). | **Fixed in code:** the pipeline lock falls back to `msvcrt` byte-range locking on Windows. |
| (same) | **Crash:** `ZoneInfoNotFoundError: Europe/Berlin` (Windows has no tz database). | **Fixed:** `tzdata` added to `requirements.txt` for Windows only. |
| `--once` output | **Crash:** `UnicodeEncodeError` printing supplier names (Windows console code page). | **Fixed:** the orchestrator writes stdout/stderr as UTF-8. |
| Tesseract | `winget install UB-Mannheim.TesseractOCR` installs it but does **not** add it to `PATH`. Without it the app still runs and **silently loses the art-book finding** (5,900 gap disappears; data health shows 63 errors). | README: Windows install line and PATH step. Worth a loud warning in the UI when OCR is missing (not done here). |

## Result after the fixes
Fresh clone, README steps, Tesseract on PATH: `--once` finishes in about 1 minute and matches `docs/NUMBERS.md` exactly (STD 614,650, CE 62,550; art book 5,900, statue 3,400, game card 6,800; 307 of 308 files parsed, 0 errors). Full test suite: same results as clean `main`; the remaining Windows errors are test clean-up (temp folders deleted while SQLite is open), not app failures.

Not covered: macOS/Linux fresh run (Tesseract language packs), React build (`npm`), portal token and mail setup.
