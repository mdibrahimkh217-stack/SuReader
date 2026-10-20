# SuReader

A lightweight, fast PDF reader for Linux in the spirit of SumatraPDF — **native, no Wine**.
Python + Qt (PyQt5/PyQt6) + PyMuPDF.

## Features
- **Right mouse button held + wheel → zoom at the pointer** (stays exactly under the cursor)
- **Start page** like SumatraPDF's "Frequently Read": an empty tab shows thumbnails of your most-opened documents (click to open, right-click to remove, "Hide frequently read" to turn it off)
- Tabs (Ctrl+O / Ctrl+W / Ctrl+Tab)
- Single page, **facing (two pages)** and **book** views (Ctrl+6 / 7 / 8)
- **Annotations:** highlight, underline, strikeout, pen, notes; delete; save in place or save as
- Text selection / copy, **search** (Ctrl+F, F3 / Shift+F3), **links** (internal, named destinations, http/mailto), Alt+Left to go back
- Separate closable panels: **Outline**, **Thumbnails**, **Bookmarks** (F6 / F7 / F8; per-file bookmarks kept in `~/.config/sumatra-linux/bookmarks.json`)
- Fit width / fit page / actual size, go to page, fullscreen, drag & drop, password-protected PDFs, ePub/XPS/CBZ viewing

## Run from source
```bash
pip install -r requirements.txt
python3 sureader.py file.pdf
```

## Install
Download from the **Releases** page:

| Package | Install |
|---|---|
| `SuReader-x86_64.AppImage` (any distro, nothing to install) | `chmod +x SuReader-x86_64.AppImage && ./SuReader-x86_64.AppImage file.pdf` |
| `sureader_<ver>_amd64.deb` (Debian / Ubuntu / Mint) | `sudo apt install ./sureader_<ver>_amd64.deb` |
| `sureader-<ver>-1.x86_64.rpm` (Fedora / openSUSE / RHEL-like) | `sudo dnf install ./sureader-<ver>-1.x86_64.rpm` |

The AppImage is built with Qt5 and bundles everything, so it also runs on older systems (glibc >= 2.28,
e.g. Ubuntu/Mint 20.04). The `.deb` / `.rpm` need Python >= 3.8 and PyQt5 or PyQt6 from your distro
(installed automatically); PyMuPDF is bundled.

Packages are built automatically from this repo by GitHub Actions. Want a package for another distro?
See [CONTRIBUTING.md](CONTRIBUTING.md). Build locally with `packaging/build_deb.sh`, `packaging/build_rpm.sh`,
`packaging/build_appimage.sh` (outputs go to `dist/`).

## Keys
| | |
|---|---|
| Tools | H hand · T select text · L highlight · U underline · K strikeout · P pen · N note · E delete annotation |
| View | Ctrl+1 actual size · Ctrl+2 fit page · Ctrl+3 fit width · Ctrl+= / Ctrl+- zoom · F11 fullscreen |
| File | Ctrl+O open · Ctrl+S save · Ctrl+Shift+S save as · Ctrl+R reload · Ctrl+G go to page |
| Other | Ctrl+D add bookmark · Ctrl+F find · Ctrl+C copy · Esc clear selection |

## Not implemented yet
Match-case search, clickable plain-text URLs, continuous/non-continuous toggle.

## License
SuReader depends on PyMuPDF (AGPL-3.0) and PyQt (GPL-3.0). Distributing it (including the AppImage) means
the project should be released under a compatible license such as **AGPL-3.0**. Pick one and add a `LICENSE` file.
