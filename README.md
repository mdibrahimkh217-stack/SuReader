# SuReader

A lightweight, fast PDF reader for Linux in the spirit of SumatraPDF — **native, no Wine**.
Python + Qt (PyQt5/PyQt6) + PyMuPDF.

## Features
- **Right mouse button held + wheel → zoom at the pointer** (stays exactly under the cursor)
- **Start page (Home):** an empty tab shows thumbnails of the 10 most recently opened documents (click to open, right-click to remove or pin, "Hide ..." to turn it off). **Pin** a book (pin icon on its thumbnail) to keep it there - pinned books are not counted in the 10. Settings > Home overview switches to "Frequently read" (most opened first)
- Tabs (Ctrl+O / Ctrl+W / Ctrl+Tab) plus a **Tabs ▾** drop-down listing every open tab, **File → Open Recent** (last 10 documents)
- Single page, **facing (two pages)** and **book** views (Ctrl+6 / 7 / 8)
- **Annotations:** highlight, underline, strikeout, pen, notes, text boxes; each tool has its own colour (Edit menu or right-click menu); delete from the right-click menu. Save asks "save to this same file?" (Yes = replace, No = choose another file); saves are written to a temporary file and verified before the original is replaced; closing with unsaved annotations asks again
- Text selection / copy, **search** (Ctrl+F, F3 / Shift+F3), **links** (internal, named destinations, http/mailto), Alt+Left to go back
- Separate closable panels: **Outline**, **Thumbnails**, **Bookmarks** (F6 / F7 / F8; per-file bookmarks kept in `~/.config/sumatra-linux/bookmarks.json`)
- Fit width / fit page / actual size, go to page, fullscreen, drag & drop, password-protected PDFs, ePub/XPS/CBZ viewing


## What's new in 2.0
- **Undo / Redo** (Edit menu, Ctrl+Z / Ctrl+Y) for every change: highlights, underlines, pen strokes, notes, text boxes, deletions, edits.
- **Settings menu:** zoom speed, mouse-wheel zoom direction (normal / inverted), dark mode (the pages keep their real colours), page render (how much of a big book is kept ready for smooth scrolling),
  bookmarks with thumbnails on/off, highlight mode.
- **Highlight modes:** *with selection* (draw a rectangle, resize / move it, ✔ or Enter to apply, ✕ or Esc to cancel),
  *with select text*, or **Automatic** (text selection over text, rectangle over images / figures; Alt forces the rectangle).
- **Remove part of a highlight / underline / strikeout:** select the text with the Select-text tool, right-click, "Remove ... from selection".
- **Text box tool** (X) - English and Bengali (any script) text; click a box to edit it.
- **Second ribbon:** Refresh, page box "22 / 100" with arrows, zoom box (presets, Fit width / Fit page, typed %), + / -.
- **Print** (Ctrl+P) with page ranges.
- **Big scanned books:** pages are rendered in the background (never freezes while scrolling), thumbnails are virtualised;
  bookmarks can show page thumbnails.

- **Settings > Opening PDFs:** tab mode (default) or window mode (each PDF in its own window, no tab bar).
- One compact ribbon: Refresh, Save, Home, tools, page box, zoom box. Highlight / underline / strikeout / pen colours are set in Edit (or from the right-click menu).

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
| `sureader_amd64.deb` (Debian / Ubuntu / Mint) | `sudo apt install ./sureader_amd64.deb` |
| `sureader.x86_64.rpm` (Fedora / openSUSE / RHEL-like) | `sudo dnf install ./sureader.x86_64.rpm` |

The AppImage is built with Qt5 and bundles everything, so it also runs on older systems (glibc >= 2.28,
e.g. Ubuntu/Mint 20.04). The `.deb` / `.rpm` need Python >= 3.8 and PyQt5 or PyQt6 from your distro
(installed automatically); PyMuPDF is bundled.

Packages are built automatically from this repo by GitHub Actions. Want a package for another distro?
See [CONTRIBUTING.md](CONTRIBUTING.md). Build locally with `packaging/build_deb.sh`, `packaging/build_rpm.sh`,
`packaging/build_appimage.sh` (outputs go to `dist/`).

## Keys
| | |
|---|---|
| Tools | H hand · T select text · L highlight · U underline · K strikeout · P pen · N note · X text box |
| View | Ctrl+1 actual size · Ctrl+2 fit page · Ctrl+3 fit width · Ctrl+= / Ctrl+- zoom · F11 fullscreen |
| File | Ctrl+O open · Ctrl+S save · Ctrl+Shift+S save as · Ctrl+R reload · Ctrl+G go to page |
| Other | Ctrl+D add bookmark · Ctrl+F find · Ctrl+C copy · Esc clear selection |

## Robustness
- Saves go to a temporary file, are verified (page count, password protection) and only then replace the original.
- PDFs whose cross-reference chain is damaged (opens with 0 pages in some readers, e.g. an incremental update whose `/Prev` points at itself) are repaired in memory when opened; Save writes a clean file.

## Not implemented yet
Match-case search, clickable plain-text URLs, continuous/non-continuous toggle, Bengali (complex-script) text in FreeText annotations of other PDF editors.

## License
SuReader is released under the **AGPL-3.0** (see `LICENSE`), as required by its dependencies PyMuPDF (AGPL-3.0) and PyQt (GPL-3.0).
<img width="1365" height="733" alt="image" src="https://github.com/user-attachments/assets/e59d5324-9e49-4eae-a087-35fe304fdfad" />

