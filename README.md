# SuReader

A lightweight, fast PDF reader for Linux in the spirit of SumatraPDF — **native, no Wine**.
Python + Qt (PyQt5/PyQt6) + PyMuPDF.

## Features
- **Right mouse button held + wheel → zoom at the pointer** (stays exactly under the cursor)
- **Start page (Home):** an empty tab shows thumbnails of the 10 most recently opened documents (click to open, right-click to remove or pin, "Hide ..." to turn it off). **Pin** a book (pin icon on its thumbnail) to keep it there - pinned books are not counted in the 10. Settings > Home overview switches to "Frequently read" (most opened first)
- A **Menu ▾** button (File, View, Edit, Settings) at the left end of the ribbon and a **Tabs ▾** drop-down listing every open tab at the right end; tabs: Ctrl+O / Ctrl+W / Ctrl+Tab; **File → Open Recent** (last 10 documents)
- **Smooth scrolling** with the mouse wheel and the keyboard (arrows, Page Up / Down, Space, Home / End); Settings > Smooth scrolling switches it off
- Single page, **facing (two pages)** and **book** views (Ctrl+6 / 7 / 8)
- **Annotations:** highlight, underline, strikeout, pen, notes, text boxes; each tool has its own colour (Edit menu or right-click menu); delete from the right-click menu. Save asks "save to this same file?" (Yes = replace, No = choose another file); saves are written to a temporary file and verified before the original is replaced; closing with unsaved annotations asks again
- Text selection / copy, **search** (Ctrl+F, F3 / Shift+F3), **links** (internal, named destinations, http/mailto), Alt+Left to go back
- Separate closable panels: **Outline**, **Thumbnails**, **Bookmarks** (F6 / F7 / F8; per-file bookmarks kept in `~/.config/sumatra-linux/bookmarks.json`)
- Fit width / fit page / actual size, go to page, fullscreen, drag & drop, password-protected PDFs, ePub/XPS/CBZ viewing


## What's new in 2.0
- **Undo / Redo** (Edit menu, Ctrl+Z / Ctrl+Y) for every change: highlights, underlines, pen strokes, notes, text boxes, deletions, edits.
- **Settings menu:** zoom speed, dark mode (the pages keep their real colours), smooth scrolling on/off,
  bookmarks with thumbnails on/off, highlight mode. The mouse wheel always zooms the same way (wheel up = zoom in, wheel down = zoom out, + / −) and about 5 % of the book around the page you read is kept ready, for every PDF - neither has a setting.
- **Highlight modes:** *with selection* (draw a rectangle, resize / move it, ✔ or Enter to apply, ✕ or Esc to cancel),
  *with select text*, or **Automatic** (text selection over text, rectangle over images / figures; Alt forces the rectangle).
- **Remove part of a highlight / underline / strikeout:** select the text with the Select-text tool, then right-click or open Menu > Edit: "Remove ... from selection" appears only when the selected text is marked.
- **Text box tool** (X) - English and Bengali (any script) text; click on the page to start typing, double click a box to edit it.
- **Ribbon:** Menu, Refresh, Save, Home, tools, **Undo** button (after Select), page box "22 / 100" with arrows, zoom box (presets, Fit width / Fit page, typed %), + / -, Tabs.
- **Print** (Ctrl+P) with page ranges.
- **Big scanned books:** sharp pages are drawn when you stop scrolling or zooming (slow scanned pages wait a little longer and prepare fewer pages around), thumbnails are virtualised;
  bookmarks can show page thumbnails.

- **Settings > Opening PDFs:** tab mode (default) or window mode (each PDF in its own window, no tab bar).
- One compact ribbon: Menu, Refresh, Save, Home, tools, Undo, page box, zoom box, Tabs. Highlight / underline / strikeout / pen colours are set in Edit (or from the right-click menu).

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

- **Text boxes:** a click with the Text box tool places the start point and you type right on the page; the box is exactly as big as its text (a long line makes a long box, each Enter one more line). Hovering or a single click never touches an existing box (hand and select tools work through it); a **double click** makes it editable and shows a thin frame with a **hanger** above it (drag to move) and **corner handles** (drag to make box and letters bigger or smaller together, never stretched). The bar above has the text colour and a trash can; click elsewhere or press Esc to keep the text. In Select mode the text of a box can be selected, copied and highlighted / underlined / struck out, and those marks move and scale with the box. They are plain, transparent, standard PDF text boxes with one colour and one size, so every PDF reader shows them. Bengali and other scripts are stored as a picture.
- **CMYK colours:** Settings > Colors holds 7 colours for each of highlight, underline, strikeout and pen. Everything is CMYK, so annotations print with exactly the chosen inks.
- **Session:** Settings > Session: start new, restore the previous session, or ask every time. Middle click closes a tab. Thumbnails grow and shrink with their panel.

- **Opening files:** SuReader runs once: a PDF opened from the file manager is added as a tab to the running window (a file that is already open just shows its tab). Every file opens at the page where you closed it. Books that are not there (e.g. an unmounted drive) stay on the start page with a grey title and show a "File not found" message when clicked.
- **Mouse:** the right button drags the page with any tool selected; a plain right click opens the menu. The Find bar is a third ribbon under the tools.

## License
SuReader is released under the **AGPL-3.0** (see `LICENSE`), as required by its dependencies PyMuPDF (AGPL-3.0) and PyQt (GPL-3.0).
