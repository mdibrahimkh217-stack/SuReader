#!/usr/bin/env python3
"""
SuReader - lightweight SumatraPDF-style PDF reader for Linux (native, no Wine).

Dependencies:  pip install pymupdf PyQt5     (PyQt6 also works)
Run:           python3 sureader.py [a.pdf b.pdf ...]

* Right mouse button held + wheel  -> zoom at the pointer position
  (press and release right button without zooming -> context menu)
* Tabs            Ctrl+O open (new tab)  Ctrl+W close  Ctrl+Tab / Ctrl+Shift+Tab switch
* Page layouts    Ctrl+6 single   Ctrl+7 facing (two pages)   Ctrl+8 book (cover alone)
* Tools           H hand  T select text  L highlight  U underline  K strikeout
                  P pen  N note  X text box   (Ctrl+C copies selection)
* Colours         Edit > Highlight / Underline / Strikeout / Pen > colour = the colour those tools use;
                  right-click on selected text > Highlight / Underline / Strikeout > colour marks it at once
* File > Open Recent  the last 10 opened documents
* Start page      empty tab shows your most-read documents (click to open, right-click to remove)
* Zoom speed      View > Zoom speed... (how much one wheel notch zooms)
* Panels          Outline (F6), Thumbnails (F7), Bookmarks (F8): each has its own close (X)
                  button and can be re-opened from the View menu
                  Ctrl+D add bookmark (right-click a bookmark to rename/delete)
* Search          Ctrl+F find, Enter / F3 next, Shift+F3 previous, Esc close
* Links           click internal / http(s) links;  Alt+Left goes back
* Save            Ctrl+S asks "save to this same file?" (Yes = replace, No = choose another file);
                  Ctrl+Shift+S save as;  closing a tab/app with unsaved annotations asks too
* Tabs button     right end of the ribbon: drop-down list of all open tabs
* Settings > Opening PDFs: tab mode (default) or window mode (each PDF in its own window, no tab bar)
* View            Ctrl+1 actual size  Ctrl+2 fit page  Ctrl+3 fit width  Ctrl+= / Ctrl+-
                  Ctrl+G go to page   Ctrl+R reload    F11 fullscreen
"""
import sys
import os
import platform
import re
import gc
import json
import contextlib
import time
import hashlib
import traceback
from bisect import bisect_right
from collections import OrderedDict

try:
    import pymupdf
except ImportError:                      # older PyMuPDF
    import fitz as pymupdf

try:
    from PyQt6.QtCore import (Qt, QTimer, QRectF, QPointF, QSize, QPoint, QRect, QObject, QUrl,
                              pyqtSignal)
    from PyQt6.QtGui import (QImage, QPainter, QColor, QAction, QActionGroup,
                             QKeySequence, QPen, QPixmap, QIcon, QDesktopServices, QPalette, QFont,
                             QFontMetrics, QIntValidator)
    from PyQt6.QtWidgets import (
        QAbstractScrollArea, QApplication, QComboBox, QFileDialog, QInputDialog,
        QLineEdit, QMainWindow, QMenu, QMessageBox, QTabWidget, QToolBar,
        QDockWidget, QListView, QListWidget, QListWidgetItem, QTreeWidget,
        QTreeWidgetItem, QLabel, QFrame, QGridLayout, QVBoxLayout, QScrollArea, QWidget,
        QToolButton, QSizePolicy, QDialog, QTextBrowser, QDialogButtonBox)
except ImportError:                      # Qt5 (older distros, e.g. glibc < 2.33)
    from PyQt5.QtCore import (Qt, QTimer, QRectF, QPointF, QSize, QPoint, QRect, QObject, QUrl,
                              pyqtSignal)
    from PyQt5.QtGui import (QImage, QPainter, QColor, QKeySequence, QPen,
                             QPixmap, QIcon, QDesktopServices, QPalette, QFont,
                             QFontMetrics, QIntValidator)
    from PyQt5.QtWidgets import (
        QAbstractScrollArea, QApplication, QComboBox, QFileDialog, QInputDialog,
        QLineEdit, QMainWindow, QMenu, QMessageBox, QTabWidget, QToolBar,
        QAction, QActionGroup, QDockWidget, QListView, QListWidget,
        QListWidgetItem, QTreeWidget, QTreeWidgetItem, QLabel, QFrame, QGridLayout,
        QVBoxLayout, QScrollArea, QWidget, QToolButton, QSizePolicy, QDialog, QTextBrowser,
        QDialogButtonBox)


try:                                      # printing is optional
    try:
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog, QAbstractPrintDialog
    except ImportError:
        from PyQt5.QtPrintSupport import QPrinter, QPrintDialog, QAbstractPrintDialog
except ImportError:
    QPrinter = QPrintDialog = QAbstractPrintDialog = None


def ev_pos(ev):
    """Event position in widget coordinates (QPoint), Qt5 and Qt6."""
    return ev.position().toPoint() if hasattr(ev, "position") else ev.pos()


def ev_global(ev):
    return ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()


def run_exec(obj, *a):
    return (obj.exec if hasattr(obj, "exec") else obj.exec_)(*a)


APP_NAME = "SuReader"
APP_VERSION = "2.1"
APP_URL = "https://github.com/mdibrahimkh217-stack/SuReader"
BASE = 96.0 / 72.0          # 100% zoom == 96 dpi, like SumatraPDF
MIN_Z, MAX_Z = 0.05 * BASE, 64 * BASE
MARGIN, GAP = 10, 10
FULL_RENDER_LIMIT = 16_000_000   # pixels; bigger pages are rendered clipped

COLORS = [("Yellow", (1.0, 0.92, 0.2)), ("Red", (0.9, 0.15, 0.15)),
          ("Green", (0.35, 0.85, 0.35)), ("Pink", (1.0, 0.5, 0.75)),
          ("Blue", (0.3, 0.55, 1.0)), ("Orange", (1.0, 0.6, 0.15)),
          ("Black", (0.0, 0.0, 0.0))]
TOOLS = [("hand", "Hand", "H"), ("select", "Select", "T"),
         ("highlight", "Highlight", "L"), ("underline", "Underline", "U"),
         ("strike", "Strikeout", "K"), ("pen", "Pen", "P"),
         ("note", "Note", "N"), ("textbox", "Textbox", "X")]
MARKUP = ("highlight", "underline", "strike")
COLOR_KINDS = ("highlight", "underline", "strike", "pen")      # tools that have their own colour
KIND_LABELS = {"highlight": "Highlight", "underline": "Underline", "strike": "Strikeout", "pen": "Pen"}
COLOR_BY_NAME = dict(COLORS)
NOTE_COLOR = COLORS[0][1]
MARKUP_TYPES = {"highlight": "Highlight", "underline": "Underline", "strike": "StrikeOut"}
MARKUP_LABELS = {"highlight": "highlight", "underline": "underline", "strike": "strikeout"}
HANDLE_CURSORS = {"n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                  "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
                  "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
                  "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor}
CURSORS = {"hand": Qt.CursorShape.OpenHandCursor, "select": Qt.CursorShape.IBeamCursor,
           "highlight": Qt.CursorShape.IBeamCursor, "underline": Qt.CursorShape.IBeamCursor,
           "strike": Qt.CursorShape.IBeamCursor, "pen": Qt.CursorShape.CrossCursor,
           "note": Qt.CursorShape.CrossCursor, "textbox": Qt.CursorShape.CrossCursor,
           "erase": Qt.CursorShape.PointingHandCursor}


def make_dark_palette():
    p = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for role, col in ((R.Window, (45, 45, 48)), (R.WindowText, (225, 225, 225)),
                      (R.Base, (30, 30, 32)), (R.AlternateBase, (45, 45, 48)),
                      (R.ToolTipBase, (60, 60, 64)), (R.ToolTipText, (225, 225, 225)),
                      (R.Text, (225, 225, 225)), (R.Button, (58, 58, 62)),
                      (R.ButtonText, (225, 225, 225)), (R.BrightText, (255, 90, 90)),
                      (R.Link, (110, 170, 255)), (R.Highlight, (60, 110, 200)),
                      (R.HighlightedText, (255, 255, 255))):
        p.setColor(role, QColor(*col))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(G.Disabled, role, QColor(125, 125, 125))
    return p


def qcolor(rgb, alpha=255):
    return QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), alpha)


class PdfView(QAbstractScrollArea):
    changed = pyqtSignal()
    modified_changed = pyqtSignal()
    loaded = pyqtSignal()
    content_changed = pyqtSignal(int)
    search_changed = pyqtSignal()
    undo_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.path = None
        self.modified = False
        self.sizes = []        # (w, h) in PDF points
        self.rows = []         # list of rows; each row is a list of page indexes (-1 = blank)
        self.row_tops, self.row_hs = [], []
        self.page_pos, self.page_row = {}, {}
        self.mode = "single"   # single | facing | book
        self.zoom = BASE
        self.cw = self.ch = 0
        self.fit = "width"     # "width" | "page" | None
        self.cache = OrderedDict()
        self.last = {}
        self.words_cache = {}
        self._fast = False
        self._right_zoomed = False
        self._pan = None
        self._press = None
        self._moved = False
        self._selecting = False
        self.sel = None        # ((page, word), (page, word))
        self._stroke = None
        self._stroke_page = None
        self._cur_shape = None
        self.rect_sel = None        # adjustable rectangle: {"page": i, "rect": Rect}
        self._rect_drag = None
        self.tool = "hand"
        self.colors = {k: COLORS[0][1] for k in COLOR_KINDS}     # colour of each tool
        self.menu_factory = None
        self.zoom_pct = 10        # % zoom change per wheel notch
        self.wheel_down_in = True  # wheel down = zoom in (False: wheel up = zoom in)
        self.hl_mode = "auto"      # highlight tool: "rect" | "text" | "auto"
        self.dark = False
        self.invert_pages = False
        self._pw = None
        self.repaired = False     # opened from an in-memory repaired copy of a damaged file
        self.links_cache = {}
        self.nav_stack = []
        self._over_link = False
        self.home = None
        self._journal = False     # PyMuPDF journal = undo/redo history of every change
        self._saved_pos = 0       # journal position that matches the file on disk
        self.touched = set()      # pages changed in this session (re-read after undo/redo)
        self.search_text = ""
        self.hits = []          # [(page, Rect)]
        self.hit_map = {}       # page -> [(hit index, Rect)]
        self.hit_idx = -1
        self.searching = False
        self._s_page = 0
        self._s_from = 0
        self._s_pending = False
        self.search_timer = QTimer(self)
        self.search_timer.setInterval(1)
        self.search_timer.timeout.connect(self._search_step)

        self.settle = QTimer(self)
        self.settle.setSingleShot(True)
        self.settle.setInterval(140)
        self.settle.timeout.connect(self._settled)
        self.low = OrderedDict()           # cheap low-resolution previews (shown while scrolling fast)
        self._need = False                 # a visible page is still waiting for its sharp rendering
        self._last_scroll = 0.0
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_step)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().setSingleStep(48)
        self.horizontalScrollBar().setSingleStep(48)
        self.viewport().setMouseTracking(True)
        self.set_tool("hand")

    # ------------------------------------------------------------ document
    @staticmethod
    def _try_repair(path):
        """For a PDF that opens with 0 pages because its cross-reference chain is damaged
        (e.g. an incremental update whose /Prev points at itself): return a repaired in-memory
        Document, or None. The file on disk is not touched."""
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        cands = []
        sx = [(m.start(), int(m.group(1))) for m in re.finditer(rb"startxref\s+(\d+)", data)]
        if len(sx) >= 2:                       # 1) /Prev that points to its own xref section
            last_off, prev_off = sx[-1][1], sx[-2][1]
            m = None
            for m in re.finditer(rb"/Prev\s+%d\b" % last_off, data):
                pass
            if m is not None and m.start() > last_off and len(str(prev_off)) == len(str(last_off)):
                num = m.group(0)[:len(m.group(0)) - len(str(last_off))] + str(prev_off).encode()
                cands.append(data[:m.start()] + num + data[m.end():])
        i = data.rfind(b"startxref")           # 2) make MuPDF rebuild the xref by scanning
        if i >= 0:
            cands.append(data[:i] + b"startxxxx" + data[i + 9:])
        pymupdf.TOOLS.mupdf_display_errors(False)
        try:
            for c in cands:
                try:
                    d = pymupdf.open(stream=c, filetype="pdf")
                    if d.page_count > 0:
                        return d
                    d.close()
                except Exception:
                    pass
        finally:
            pymupdf.TOOLS.mupdf_display_errors(True)
        return None

    def load(self, path, keep=False):
        doc = pymupdf.open(path)
        repaired = False
        if doc.page_count == 0 and doc.is_pdf and not doc.needs_pass:
            fixed = self._try_repair(path)
            if fixed is not None:
                doc.close()
                doc, repaired = fixed, True
        pw = None
        if doc.needs_pass:
            pw = self._pw if keep else None        # reload of the same file: reuse the password
            if not (pw and doc.authenticate(pw)):
                pw, ok = QInputDialog.getText(self, "Password", "Document is encrypted:",
                                              QLineEdit.EchoMode.Password)
                if not ok or not doc.authenticate(pw):
                    raise ValueError("Wrong password")
        if doc.page_count == 0:
            doc.close()
            raise ValueError("This document has no readable pages (the file may be damaged).")
        self._pw = pw
        self.repaired = repaired
        prev = self.current_page() if (keep and self.doc is not None and not self.doc.is_closed) else 0
        old, self.doc = self.doc, doc
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.path = path
        self._journal, self._saved_pos, self.touched = False, 0, set()
        if doc.is_pdf:
            try:
                doc.journal_enable()
                self._journal = True
            except Exception:
                pass
        if self.home is not None:
            self.home.hide()
        self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        self.cache.clear()
        self.last.clear()
        self.words_cache.clear()
        self.links_cache.clear()
        self.nav_stack = []
        self.clear_search()
        self.sel = None
        if not keep:
            self.fit = "width"
        self._build_rows()
        self._relayout()
        if self.fit:
            self._apply_fit(prev)
        else:
            self.goto_page(prev)
        if self.modified:
            self.modified = False
            self.modified_changed.emit()
        self.viewport().update()
        self.changed.emit()
        self.loaded.emit()

    def set_dark(self, dark, invert):
        """Dark UI background; `invert` also inverts the rendered page colours."""
        changed = invert != self.invert_pages
        self.dark, self.invert_pages = dark, invert
        if changed:
            self.cache.clear()
            self.last.clear()
        if self.home is not None:
            self.home.set_dark(dark)
        self.viewport().update()

    def attach_home(self, home):
        self.home = home
        home.setGeometry(self.viewport().rect())
        home.show()

    @property
    def page_count(self):
        return len(self.sizes)

    # ----------------------------------------------------------- save/dirty
    def _set_modified(self, v=True):
        if self.modified != v:
            self.modified = v
            self.modified_changed.emit()

    def write_to(self, path):
        """Safely write the in-memory document (including annotations) to `path`.
        Written to a temporary file next to the target, verified, and only then moved over
        the target, so a failed or corrupt write can never damage an existing file."""
        folder = os.path.dirname(os.path.abspath(path))
        tmp = os.path.join(folder, ".%s.sureader-tmp" % os.path.basename(path))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            kw = {"garbage": 0, "deflate": False}
            if self._pw:
                # password-protected document: MuPDF forgets the encryption once authenticated,
                # so encrypt the saved file again with the password the user entered
                kw.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=self._pw,
                          owner_pw=self._pw, permissions=self.doc.permissions)
            else:
                kw["encryption"] = pymupdf.PDF_ENCRYPT_KEEP     # keeps owner-only protection
            self.doc.save(tmp, **kw)
            chk = pymupdf.open(tmp)
            try:
                if self._pw and not chk.needs_pass:
                    raise ValueError("verification failed: the password protection was not preserved")
                if chk.needs_pass and self._pw:
                    chk.authenticate(self._pw)
                if not chk.needs_pass and (not chk.is_pdf or chk.page_count != self.page_count):
                    raise ValueError("verification failed: the written file has %d pages instead of %d"
                                     % (chk.page_count, self.page_count))
            finally:
                chk.close()
            os.replace(tmp, path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise
        finally:
            QApplication.restoreOverrideCursor()

    def _mark_saved(self):
        self._saved_pos = self.doc.journal_position()[0] if self._journal else 0
        self._set_modified(False)
        self.repaired = False
        self.undo_changed.emit()

    def save(self, reload=False):
        """Replace the original file with the annotated document (raises on failure).
        The open document stays loaded, so undo/redo keeps working after saving."""
        self.write_to(self.path)
        self._mark_saved()
        if reload:
            self.load(self.path, keep=True)

    def save_as(self, path, reload=False):
        """Save a copy under a new name (raises on failure); this tab continues with the new file."""
        self.write_to(path)
        self._mark_saved()
        if os.path.abspath(path) != os.path.abspath(self.path or ""):
            self.path = path
            self.changed.emit()
            self.loaded.emit()
        if reload:
            self.load(path, keep=True)

    # ---------------------------------------------------------- undo / redo
    @contextlib.contextmanager
    def op(self, name):
        """Group every change made inside the block into ONE undoable step."""
        started = False
        if self._journal:
            try:
                if self.doc.journal_position()[0] < self._saved_pos:
                    self._saved_pos = -1          # history branched away from the saved file
                self.doc.journal_start_op(name)
                started = True
            except Exception:
                started = False
        try:
            yield
        finally:
            if started:
                try:
                    self.doc.journal_stop_op()
                except Exception:
                    pass
        self._changed()

    def _changed(self):
        if self._journal:
            try:
                self._set_modified(self.doc.journal_position()[0] != self._saved_pos)
            except Exception:
                self._set_modified(True)
        else:
            self._set_modified(True)
        self.undo_changed.emit()

    def _touch(self, pages):
        self.touched.update(pages)
        for i in pages:
            self.invalidate(i)

    def can_undo(self):
        try:
            return self._journal and bool(self.doc.journal_can_do()["undo"])
        except Exception:
            return False

    def can_redo(self):
        try:
            return self._journal and bool(self.doc.journal_can_do()["redo"])
        except Exception:
            return False

    def undo_name(self):
        try:
            return self.doc.journal_op_name(self.doc.journal_position()[0] - 1)
        except Exception:
            return ""

    def redo_name(self):
        try:
            return self.doc.journal_op_name(self.doc.journal_position()[0])
        except Exception:
            return ""

    def _journal_step(self, direction):
        if direction < 0 and not self.can_undo():
            return False
        if direction > 0 and not self.can_redo():
            return False
        self.sel = None
        self.rect_sel = None
        self._rect_drag = None
        gc.collect()                       # no stray Page objects may survive an undo/redo
        (self.doc.journal_undo if direction < 0 else self.doc.journal_redo)()
        for i in sorted(self.touched):
            try:
                pg = self.doc.load_page(i)
                self.doc.reload_page(pg)
                del pg
            except Exception:
                pass
            self.invalidate(i)
        self._changed()
        return True

    def undo(self):
        return self._journal_step(-1)

    def redo(self):
        return self._journal_step(1)

    # -------------------------------------------------------------- layout
    def _build_rows(self):
        n = len(self.sizes)
        if n == 0:
            self.rows = []
        elif self.mode == "single":
            self.rows = [[i] for i in range(n)]
        elif self.mode == "facing":
            self.rows = [[i, i + 1] if i + 1 < n else [i] for i in range(0, n, 2)]
        else:  # book: cover page alone on the right
            self.rows = [[-1, 0]] + [[i, i + 1] if i + 1 < n else [i] for i in range(1, n, 2)]

    def _psize(self, row, i):
        return self.sizes[i if i >= 0 else row[1]]

    def _relayout(self):
        if not self.sizes:
            return
        z = self.zoom
        widths, heights = [], []
        for row in self.rows:
            ws = [self._psize(row, i)[0] * z for i in row]
            widths.append(sum(ws) + GAP * (len(row) - 1))
            heights.append(max(self.sizes[i][1] for i in row if i >= 0) * z)
        maxw = max(widths)
        self.cw = int(maxw + 2 * MARGIN)
        self.row_tops, self.page_pos, self.page_row = [], {}, {}
        y = MARGIN
        for r, row in enumerate(self.rows):
            self.row_tops.append(y)
            x = (self.cw - (widths[r] if self.mode == "single" else maxw)) / 2.0
            for i in row:
                if i >= 0:
                    self.page_pos[i] = (x, y)
                    self.page_row[i] = r
                x += self._psize(row, i)[0] * z + GAP
            y += heights[r] + GAP
        self.row_hs = heights
        self.ch = int(y - GAP + MARGIN)
        vp = self.viewport().size()
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setRange(0, max(0, self.cw - vp.width()))
        hs.setPageStep(vp.width())
        vs.setRange(0, max(0, self.ch - vp.height()))
        vs.setPageStep(vp.height())

    def _x_off(self):
        return max(0, (self.viewport().width() - self.cw) // 2)

    def _locate(self, mx, my):
        """Viewport point -> (page, x_pt, y_pt) in PDF points."""
        if not self.row_tops:
            return 0, 0.0, 0.0
        xc = self.horizontalScrollBar().value() + mx - self._x_off()
        yc = self.verticalScrollBar().value() + my
        r = max(0, min(len(self.row_tops) - 1, bisect_right(self.row_tops, yc) - 1))
        z = self.zoom
        best = None
        for i in self.rows[r]:
            if i < 0:
                continue
            x, _ = self.page_pos[i]
            w = self.sizes[i][0] * z
            d = 0 if x <= xc <= x + w else min(abs(xc - x), abs(xc - x - w))
            if best is None or d < best[0]:
                best = (d, i)
        i = best[1]
        x, y = self.page_pos[i]
        return i, (xc - x) / z, (yc - y) / z

    # ---------------------------------------------------------------- zoom
    def set_zoom(self, new_zoom, anchor=None, keep_fit=False):
        """Zoom so the document point under `anchor` (viewport coords)
        stays exactly under that same viewport position."""
        if not self.sizes:
            return
        new_zoom = max(MIN_Z, min(MAX_Z, new_zoom))
        if anchor is None:
            anchor = (self.viewport().width() // 2, self.viewport().height() // 2)
        mx, my = anchor
        i, px, py = self._locate(mx, my)
        self.zoom = new_zoom
        if not keep_fit:
            self.fit = None
        self._relayout()
        x, y = self.page_pos[i]
        self.horizontalScrollBar().setValue(round(x + px * new_zoom + self._x_off() - mx))
        self.verticalScrollBar().setValue(round(y + py * new_zoom - my))
        self.viewport().update()
        self.changed.emit()

    def zoom_by(self, factor, anchor=None):
        self._fast = True
        self.settle.start()
        self.set_zoom(self.zoom * factor, anchor)

    def _fit_zoom(self, cur):
        vp = self.viewport().size()
        if self.mode == "single":
            wpt, hpt = self.sizes[cur]
            cols = 1
        else:
            wpt = max(sum(self._psize(r, i)[0] for i in r) for r in self.rows)
            row = self.rows[self.page_row.get(cur, 0)]
            hpt = max(self.sizes[i][1] for i in row if i >= 0)
            cols = max(len(r) for r in self.rows)
        zw = (vp.width() - 2 * MARGIN - GAP * (cols - 1)) / max(wpt, 1)
        if self.fit == "page":
            return min(zw, (vp.height() - 2 * MARGIN) / max(hpt, 1))
        return zw

    def _apply_fit(self, cur=None):
        if not self.sizes:
            return
        if not self.row_tops:
            self._relayout()
        if cur is None:
            cur = self.current_page()
        if self.fit:
            self.zoom = max(MIN_Z, min(MAX_Z, self._fit_zoom(cur)))
        self._relayout()
        self.goto_page(cur)
        self.viewport().update()
        self.changed.emit()

    def fit_width(self):
        self.fit = "width"
        self._apply_fit()

    def fit_page(self):
        self.fit = "page"
        self._apply_fit()

    def actual_size(self):
        self.set_zoom(BASE)

    def set_view_mode(self, mode):
        if mode == self.mode or not self.sizes:
            self.mode = mode
            return
        cur = self.current_page()
        self.mode = mode
        self._build_rows()
        self._relayout()
        if self.fit:
            self._apply_fit(cur)
        else:
            self.goto_page(cur)
        self.viewport().update()
        self.changed.emit()

    def _settled(self):
        self._fast = False
        self.viewport().update()
        self._schedule_render()

    # ---------------------------------------------- background page rendering
    def _schedule_render(self, delay=0):
        if not self._render_timer.isActive():
            self._render_timer.start(delay)

    def _visible_pages(self):
        if not self.row_tops:
            return []
        vs, vh = self.verticalScrollBar().value(), self.viewport().height()
        out = []
        for r in range(max(0, bisect_right(self.row_tops, vs) - 1), len(self.rows)):
            top = self.row_tops[r] - vs
            if top > vh:
                break
            if top + self.row_hs[r] >= 0:
                out += [i for i in self.rows[r] if i >= 0]
        return out

    def _render_exact(self, i, key, z, dpr):
        try:
            pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(z * dpr, z * dpr), alpha=False)
            img = self._qimage(pix)
            if self.invert_pages:
                img.invertPixels()
        except Exception:
            img = QImage(8, 8, QImage.Format.Format_RGB32)       # unreadable page: don't retry forever
            img.fill(QColor("white"))
        self.cache[key] = img
        while len(self.cache) > 14:
            self.cache.popitem(last=False)
        self.last[i] = (z, img)

    def _render_low(self, i, z, dpr):
        s_ = max(0.12, min(z * 0.3, 0.6))
        try:
            pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(s_, s_), alpha=False)
            img = self._qimage(pix)
            if self.invert_pages:
                img.invertPixels()
        except Exception:
            img = QImage(8, 8, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
        self.low[i] = img
        while len(self.low) > 160:
            self.low.popitem(last=False)

    def _render_step(self):
        """Render ONE page (the one nearest the middle of the window), then yield to the event loop.
        While the user is scrolling only quick low-resolution previews are made; the sharp rendering
        follows when scrolling pauses. The window therefore never freezes on slow (scanned) pages."""
        if self.doc is None or not self.sizes:
            return
        scrolling = self._fast or (time.monotonic() - self._last_scroll) < 0.12
        dpr, z = self.devicePixelRatioF(), self.zoom
        vh, vs = self.viewport().height(), self.verticalScrollBar().value()
        vis = self._visible_pages()
        vis.sort(key=lambda i: abs(self.page_pos[i][1] - vs + self.sizes[i][1] * z / 2 - vh / 2))
        cands = list(vis)
        if not scrolling and vis:                         # idle: also prepare the neighbours
            lo, hi = min(vis), max(vis)
            cands += [i for i in (hi + 1, lo - 1) if 0 <= i < len(self.sizes)]
        for i in cands:
            if self.sizes[i][0] * z * dpr * self.sizes[i][1] * z * dpr > FULL_RENDER_LIMIT:
                continue
            key = (i, round(z, 4), dpr, self.invert_pages)
            if key in self.cache:
                continue
            if scrolling:
                if i not in self.last and i not in self.low:
                    self._render_low(i, z, dpr)
                    self.viewport().update()
                    self._schedule_render(30)
                    return
                continue
            self._render_exact(i, key, z, dpr)
            self.viewport().update()
            self._schedule_render(0)
            return

    # ---------------------------------------------------------- navigation
    def current_page(self):
        if not self.row_tops:
            return 0
        y = self.verticalScrollBar().value() + self.viewport().height() // 3
        r = max(0, min(len(self.row_tops) - 1, bisect_right(self.row_tops, y) - 1))
        return next(i for i in self.rows[r] if i >= 0)

    def goto_page(self, i):
        if not self.row_tops:
            return
        i = max(0, min(len(self.sizes) - 1, i))
        self.verticalScrollBar().setValue(int(self.row_tops[self.page_row[i]] - MARGIN))

    def goto_row_offset(self, d):
        if not self.row_tops:
            return
        r = max(0, min(len(self.rows) - 1, self.page_row[self.current_page()] + d))
        self.goto_page(next(i for i in self.rows[r] if i >= 0))

    def _scrolled(self):
        self._last_scroll = time.monotonic()
        self.settle.start()
        self.viewport().update()
        self.changed.emit()

    # --------------------------------------------------------------- tools
    def set_tool(self, tool):
        self.tool = tool
        self._pan = None
        self._over_link = False
        self.rect_sel = None
        self._rect_drag = None
        self._cur_shape = None
        self.sel = None
        self.viewport().setCursor(CURSORS.get(tool, Qt.CursorShape.ArrowCursor))

    def _need_pdf(self):
        if self.doc is not None and self.doc.is_pdf:
            return True
        QMessageBox.information(self, "Annotations", "Annotations are supported for PDF files only.")
        return False

    def invalidate(self, i):
        for k in [k for k in self.cache if k[0] == i]:
            del self.cache[k]
        self.low.pop(i, None)                 # the old image stays on screen until the new one is ready
        self.viewport().update()
        self._schedule_render()
        self.content_changed.emit(i)

    # ------------------------------------------------------- text selection
    def words(self, i):
        w = self.words_cache.get(i)
        if w is None:
            try:
                w = self.doc[i].get_text("words")
            except Exception:
                w = []
            self.words_cache[i] = w
        return w

    def word_at(self, i, x, y):
        best = None
        for k, w in enumerate(self.words(i)):
            dx = max(w[0] - x, 0, x - w[2])
            dy = max(w[1] - y, 0, y - w[3])
            d = dx * dx + 4 * dy * dy
            if best is None or d < best[0]:
                best = (d, k)
        return None if best is None else best[1]

    def _sel_norm(self):
        if not self.sel:
            return None
        a, b = self.sel
        return (a, b) if a <= b else (b, a)

    def _sel_span(self, i):
        (pa, ia), (pb, ib) = self._sel_norm()
        ws = self.words(i)
        return (ia if i == pa else 0), (ib if i == pb else len(ws) - 1)

    def sel_rects(self, i):
        n = self._sel_norm()
        if not n or i < n[0][0] or i > n[1][0]:
            return []
        ws = self.words(i)
        lo, hi = self._sel_span(i)
        rects, cur, key = [], None, None
        for k in range(lo, hi + 1):
            w = ws[k]
            kk = (w[5], w[6])
            if kk == key:
                cur = [min(cur[0], w[0]), min(cur[1], w[1]), max(cur[2], w[2]), max(cur[3], w[3])]
            else:
                if cur:
                    rects.append(pymupdf.Rect(*cur))
                cur, key = [w[0], w[1], w[2], w[3]], kk
        if cur:
            rects.append(pymupdf.Rect(*cur))
        return rects

    def sel_text(self):
        n = self._sel_norm()
        if not n:
            return ""
        out = []
        for i in range(n[0][0], n[1][0] + 1):
            ws = self.words(i)
            lo, hi = self._sel_span(i)
            key = None
            for k in range(lo, hi + 1):
                w = ws[k]
                kk = (w[5], w[6])
                if key is not None:
                    out.append(" " if kk == key else "\n")
                out.append(w[4])
                key = kk
            if i != n[1][0]:
                out.append("\n")
        return "".join(out).strip()

    def copy_selection(self):
        t = self.sel_text()
        if t:
            QApplication.clipboard().setText(t)

    # ---------------------------------------------------------- annotations
    def markup_selection(self, kind):
        """Apply highlight / underline / strikeout to the current selection."""
        n = self._sel_norm()
        if not n or not self._need_pdf():
            return False
        pages = [i for i in range(n[0][0], n[1][0] + 1) if self.sel_rects(i)]
        if not pages:
            self.sel = None
            self.viewport().update()
            return False
        label = {"highlight": "Highlight", "underline": "Underline", "strike": "Strikeout"}[kind]
        done = []
        with self.op(label):
            for i in pages:
                page = self.doc[i]
                fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                      "strike": page.add_strikeout_annot}[kind]
                a = fn(quads=self.sel_rects(i))
                if a is None:
                    continue
                a.set_colors(stroke=self.colors[kind])
                a.update()
                done.append(i)
        self._touch(done)
        self.sel = None
        self.viewport().update()
        return bool(done)

    def _finish_stroke(self):
        pts, i = self._stroke, self._stroke_page
        self._stroke = self._stroke_page = None
        if len(pts) >= 2 and self._need_pdf():
            with self.op("Pen stroke"):
                page = self.doc[i]
                a = page.add_ink_annot([[(float(x), float(y)) for x, y in pts]])
                a.set_border(width=1.8)
                a.set_colors(stroke=self.colors["pen"])
                a.update()
            self._touch([i])
        self.viewport().update()

    def add_note(self, i, x, y, text):
        with self.op("Note"):
            page = self.doc[i]
            a = page.add_text_annot(pymupdf.Point(x, y), text, icon="Note")
            a.set_colors(stroke=NOTE_COLOR)
            a.update()
        self._touch([i])

    def note_at(self, pos):
        """Add a note where the mouse was (right-click menu); the Note tool is not switched on."""
        if self.doc is None or not self.sizes or not self._need_pdf():
            return
        i, x, y = self._locate(pos.x(), pos.y())
        text, ok = QInputDialog.getMultiLineText(self, "Note", "Note text:")
        if ok and text.strip():
            self.add_note(i, x, y, text)

    def textbox_at(self, pos):
        """Add a text box (default size) where the mouse was (right-click menu)."""
        if self.doc is None or not self.sizes or not self._need_pdf():
            return
        i, x, y = self._locate(pos.x(), pos.y())
        self._finish_textbox({"page": i, "rect": pymupdf.Rect(x, y, x, y), "p0": (x, y)})

    def annot_under(self, pos):
        """Smallest annotation under viewport point `pos` -> (page, annot) or (None, None)."""
        if self.doc is None or not self.doc.is_pdf or not self.sizes:
            return None, None
        i, x, y = self._locate(pos.x(), pos.y())
        page = self.doc[i]
        pt = pymupdf.Point(x, y)
        best = None
        for a in page.annots():
            if a.type[1] in ("Popup", "Widget", "Link"):
                continue
            r = a.rect
            if pt in pymupdf.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2):
                area = r.width * r.height
                if best is None or area <= best[0]:
                    best = (area, a)
        return (page, best[1]) if best else (None, None)

    def delete_annot(self, page, annot):
        idx = page.number
        with self.op("Delete annotation"):
            page.delete_annot(annot)
        self._touch([idx])

    # --------------------------------------------------- rectangle selection
    def _vp_to_pt(self, i, pos):
        px, py = self.page_pos[i]
        z = self.zoom
        return ((pos.x() - self._x_off() - px + self.horizontalScrollBar().value()) / z,
                (pos.y() - py + self.verticalScrollBar().value()) / z)

    def _rect_vp(self, i, r):
        px, py = self.page_pos[i]
        z = self.zoom
        ox = self._x_off() - self.horizontalScrollBar().value()
        oy = -self.verticalScrollBar().value()
        return QRectF(ox + px + r.x0 * z, oy + py + r.y0 * z, r.width * z, r.height * z)

    @staticmethod
    def _handle_points(qr):
        cx, cy = qr.center().x(), qr.center().y()
        return {"nw": QPointF(qr.left(), qr.top()), "n": QPointF(cx, qr.top()),
                "ne": QPointF(qr.right(), qr.top()), "e": QPointF(qr.right(), cy),
                "se": QPointF(qr.right(), qr.bottom()), "s": QPointF(cx, qr.bottom()),
                "sw": QPointF(qr.left(), qr.bottom()), "w": QPointF(qr.left(), cy)}

    @staticmethod
    def _rect_buttons(qr):
        w, h = 28, 24
        y = qr.top() - h - 6
        if y < 2:
            y = qr.bottom() + 6
        cancel = QRectF(qr.right() - w, y, w, h)
        ok = QRectF(qr.right() - 2 * w - 6, y, w, h)
        return ok, cancel

    def _rect_hit(self, pos):
        """What is under `pos` for the adjustable rectangle: 'ok' | 'cancel' | handle | 'inside' | None."""
        rs = self.rect_sel
        if not rs:
            return None
        qr = self._rect_vp(rs["page"], rs["rect"])
        pt = QPointF(pos)
        ok, cancel = self._rect_buttons(qr)
        if ok.contains(pt):
            return "ok"
        if cancel.contains(pt):
            return "cancel"
        for name, c in self._handle_points(qr).items():
            if abs(pt.x() - c.x()) <= 7 and abs(pt.y() - c.y()) <= 7:
                return name
        return "inside" if qr.contains(pt) else None

    def _has_text_at(self, i, x, y, tol=2.0):
        for w in self.words(i):
            if w[0] - tol <= x <= w[2] + tol and w[1] - tol <= y <= w[3] + tol:
                return True
        return False

    def _highlight_mode_at(self, i, x, y, mods=None):
        """'text' or 'rect' for a highlight drag starting at (x, y) of page i."""
        m = self.hl_mode
        if m in ("rect", "text"):
            return m
        if mods is not None and mods & Qt.KeyboardModifier.AltModifier:
            return "rect"                      # Alt forces the rectangle even over text
        return "text" if self._has_text_at(i, x, y) else "rect"

    def _press_highlight(self, pos, mods):
        i, x, y = self._locate(pos.x(), pos.y())
        if self.rect_sel is not None:
            hit = self._rect_hit(pos)
            if hit == "ok":
                self.apply_rect_highlight()
                return
            if hit == "cancel":
                self.rect_sel = None
                self.viewport().update()
                return
            if hit is not None:
                self._rect_drag = {"kind": "move" if hit == "inside" else "handle", "handle": hit,
                                   "page": self.rect_sel["page"], "p0": (x, y),
                                   "orig": pymupdf.Rect(self.rect_sel["rect"])}
                return
            self.rect_sel = None               # clicked elsewhere: start a new one
        if self._highlight_mode_at(i, x, y, mods) == "rect":
            self._rect_drag = {"kind": "new", "page": i, "p0": (x, y), "rect": pymupdf.Rect(x, y, x, y)}
            self.viewport().update()
        else:
            k = self.word_at(i, x, y)
            self.sel = None if k is None else ((i, k), (i, k))
            self._selecting = k is not None
            self.viewport().update()

    def _drag_rect(self, pos):
        d = self._rect_drag
        i = d["page"]
        x, y = self._vp_to_pt(i, pos)
        W, H = self.sizes[i]
        x, y = min(max(x, 0.0), W), min(max(y, 0.0), H)
        kind = d["kind"]
        if kind in ("new", "newtext"):
            x0, y0 = d["p0"]
            d["rect"] = pymupdf.Rect(min(x0, x), min(y0, y), max(x0, x), max(y0, y))
            return
        o = d["orig"]
        if kind == "move":
            dx, dy = x - d["p0"][0], y - d["p0"][1]
            dx = min(max(dx, -o.x0), W - o.x1)
            dy = min(max(dy, -o.y0), H - o.y1)
            r = pymupdf.Rect(o.x0 + dx, o.y0 + dy, o.x1 + dx, o.y1 + dy)
        else:
            name = d["handle"]
            x0, y0, x1, y1 = o.x0, o.y0, o.x1, o.y1
            if "w" in name:
                x0 = x
            if "e" in name:
                x1 = x
            if "n" in name:
                y0 = y
            if "s" in name:
                y1 = y
            r = pymupdf.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self.rect_sel["rect"] = r

    def _finish_rect_drag(self):
        d, self._rect_drag = self._rect_drag, None
        if d is None:
            return
        if d["kind"] == "new":
            r = d["rect"]
            self.rect_sel = {"page": d["page"], "rect": r} if (r.width >= 6 and r.height >= 6) else None
        elif d["kind"] == "newtext":
            self._finish_textbox(d)

    def apply_rect_highlight(self):
        """Turn the adjustable rectangle into a highlight annotation."""
        rs = self.rect_sel
        if not rs or not self._need_pdf():
            return False
        i, r = rs["page"], pymupdf.Rect(rs["rect"])
        with self.op("Highlight (area)"):
            page = self.doc[i]                  # keep the page alive while the annotation is edited
            # a translucent rectangle (a real Highlight annotation would bulge past the chosen area)
            a = page.add_rect_annot(r)
            a.set_colors(stroke=self.colors["highlight"], fill=self.colors["highlight"])
            a.set_border(width=0)
            a.set_opacity(0.4)
            a.update()
        self.rect_sel = None
        self._touch([i])
        self.viewport().update()
        return True

    def cancel_rect(self):
        self.rect_sel = None
        self._rect_drag = None
        self.viewport().update()

    # ------------------------------------------------------------- text boxes
    def _textbox_color(self):
        return (0.0, 0.0, 0.0)

    @staticmethod
    def _is_latin1(text):
        try:
            text.encode("latin-1")
            return True
        except UnicodeEncodeError:
            return False

    def _render_text_image(self, text, width_pt, rgb):
        """Draw `text` with Qt (full Unicode / Bengali shaping) -> (QImage, width_pt, height_pt)."""
        S = 4                                           # 4x supersampling (288 dpi)
        font = QFont(QApplication.font())
        font.setPixelSize(12 * S)
        flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        wpx = max(40 * S, int(width_pt * S))
        br = QFontMetrics(font).boundingRect(QRect(0, 0, wpx - 2 * S, 100000), flags, text)
        hpx = max(br.height() + 2 * S, 18 * S)
        img = QImage(wpx, hpx, QImage.Format.Format_ARGB32)
        img.fill(0)
        pnt = QPainter(img)
        pnt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pnt.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pnt.setFont(font)
        pnt.setPen(qcolor(rgb))
        pnt.drawText(QRectF(S, S, wpx - 2 * S, hpx - S), flags, text)
        pnt.end()
        return img, wpx / S, hpx / S

    def _set_image_appearance(self, annot, img, w_pt, h_pt):
        """Give `annot` an appearance stream that shows the QImage `img` (with transparency)."""
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes() if hasattr(img, "sizeInBytes") else img.byteCount())
        bgra = bytes(ptr)
        w, h = img.width(), img.height()
        rgb = bytearray(w * h * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
        doc = self.doc
        # PyMuPDF 1.24's journalling check raises while an operation is open, although creating
        # objects inside the operation is exactly what we want (one undo step) -> skip that check
        orig = getattr(pymupdf, "JM_have_operation", None)
        if orig is not None:
            pymupdf.JM_have_operation = lambda pdf: 1
        try:
            xs = doc.get_new_xref()
            doc.update_object(xs, "<</Type/XObject/Subtype/Image/Width %d/Height %d/ColorSpace/DeviceGray"
                                   "/BitsPerComponent 8>>" % (w, h))
            doc.update_stream(xs, bytes(bgra[3::4]), compress=True)
            xi = doc.get_new_xref()
            doc.update_object(xi, "<</Type/XObject/Subtype/Image/Width %d/Height %d/ColorSpace/DeviceRGB"
                                   "/BitsPerComponent 8/SMask %d 0 R>>" % (w, h, xs))
            doc.update_stream(xi, bytes(rgb), compress=True)
            xf = doc.get_new_xref()
            doc.update_object(xf, "<</Type/XObject/Subtype/Form/BBox[0 0 %g %g]"
                                  "/Resources<</XObject<</Im0 %d 0 R>>>>>>" % (w_pt, h_pt, xi))
            doc.update_stream(xf, ("q %g 0 0 %g 0 0 cm /Im0 Do Q" % (w_pt, h_pt)).encode())
            doc.xref_set_key(annot.xref, "AP", "<</N %d 0 R>>" % xf)
        finally:
            if orig is not None:
                pymupdf.JM_have_operation = orig

    def _create_textbox(self, page, rect, text):
        """Create the annotation (call inside an op). Latin text -> a standard FreeText annotation;
        other scripts -> a FreeText whose appearance is drawn by Qt, so Bengali etc. render correctly."""
        col = self._textbox_color()
        rect = pymupdf.Rect(rect)
        if self._is_latin1(text):
            width = max(rect.width, 40)
            lines = 0
            for para in text.split("\n"):
                tl = pymupdf.get_text_length(para or " ", fontname="helv", fontsize=12)
                lines += max(1, int(tl / max(width - 8, 1)) + 1)
            rect.y1 = max(rect.y1, rect.y0 + lines * 14.5 + 6)
            rect.x1 = max(rect.x1, rect.x0 + 40)
            a = page.add_freetext_annot(rect, text, fontsize=12, fontname="helv", text_color=col,
                                        fill_color=None, align=0)
            a.update()
        else:
            img, w_pt, h_pt = self._render_text_image(text, max(rect.width, 40), col)
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + w_pt, rect.y0 + max(rect.height, h_pt))
            a = page.add_freetext_annot(rect, " ", fontsize=12, fontname="helv", text_color=(0, 0, 0),
                                        fill_color=None, align=0)
            self._set_image_appearance(a, img, rect.width, rect.height)
            a.set_info(content=text, subject="SuReader-image-text")
        return a

    def add_textbox(self, i, rect, text):
        if not self._need_pdf():
            return False
        W, H = self.sizes[i]
        rect = pymupdf.Rect(rect)
        rect.x1, rect.y1 = min(rect.x1, W), min(rect.y1, H)
        with self.op("Text box"):
            page = self.doc[i]
            self._create_textbox(page, rect, text)
        self._touch([i])
        return True

    def _finish_textbox(self, d):
        i, r = d["page"], d["rect"]
        W, H = self.sizes[i]
        if r.width < 12 or r.height < 12:                   # a plain click: default size
            x, y = d["p0"]
            r = pymupdf.Rect(x, y, min(x + 220, W), min(y + 50, H))
        text, ok = QInputDialog.getMultiLineText(self, "Text box", "Text:")
        if ok and text.strip():
            self.add_textbox(i, r, text)
        self.viewport().update()

    def edit_textbox(self, page, annot):
        old = annot.info.get("content", "")
        text, ok = QInputDialog.getMultiLineText(self, "Text box", "Edit text:", old)
        if not ok or not text.strip() or text == old:
            return
        rect, i = pymupdf.Rect(annot.rect), page.number
        with self.op("Edit text box"):
            page.delete_annot(annot)
            self._create_textbox(page, rect, text)
        self._touch([i])

    def edit_textbox_xref(self, i, xref):
        page = self.doc[i]
        a = page.load_annot(xref)
        if a is not None:
            self.edit_textbox(page, a)

    # ------------------------------------- remove (part of) a markup annotation
    @staticmethod
    def _annot_quad_rects(a):
        v = a.vertices or []
        return [pymupdf.Quad(v[k], v[k + 1], v[k + 2], v[k + 3]).rect for k in range(0, len(v) - 3, 4)]

    @staticmethod
    def _subtract(rect, cuts):
        """`rect` minus the horizontal spans of the `cuts` that lie on the same text line."""
        parts = [pymupdf.Rect(rect)]
        for c in cuts:
            if min(rect.y1, c.y1) - max(rect.y0, c.y0) < 0.5 * min(rect.height, c.height):
                continue
            new = []
            for r in parts:
                if c.x1 <= r.x0 or c.x0 >= r.x1:
                    new.append(r)
                    continue
                if c.x0 - r.x0 > 0.5:
                    new.append(pymupdf.Rect(r.x0, r.y0, c.x0, r.y1))
                if r.x1 - c.x1 > 0.5:
                    new.append(pymupdf.Rect(c.x1, r.y0, r.x1, r.y1))
            parts = new
        return parts

    def _plan_remove(self, kind):
        """Annotations of `kind` touched by the text selection -> list of (page, xref, colours, opacity, rest)."""
        n = self._sel_norm()
        if not n or self.doc is None or not self.doc.is_pdf:
            return []
        want, plans = MARKUP_TYPES[kind], []
        for i in range(n[0][0], n[1][0] + 1):
            cuts = self.sel_rects(i)
            if not cuts:
                continue
            page = self.doc[i]
            for a in page.annots():
                if a.type[1] != want:
                    continue
                rest, changed = [], False
                for q in self._annot_quad_rects(a):
                    parts = self._subtract(q, cuts)
                    if len(parts) != 1 or abs(parts[0].x0 - q.x0) > 0.01 or abs(parts[0].x1 - q.x1) > 0.01:
                        changed = True
                    rest.extend(parts)
                if changed:
                    plans.append((i, a.xref, dict(a.colors), a.opacity, rest))
            del page
        return plans

    def markup_overlaps(self, kind):
        return bool(self._plan_remove(kind))

    def remove_markup_from_selection(self, kind):
        """Remove highlight / underline / strikeout from the selected text only; the rest stays."""
        plans = self._plan_remove(kind)
        if not plans:
            return 0
        pages = []
        with self.op("Remove " + MARKUP_LABELS[kind]):
            for i, xref, colors, opacity, rest in plans:
                page = self.doc[i]
                old = page.load_annot(xref)
                page.delete_annot(old)
                del old
                if rest:
                    fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                          "strike": page.add_strikeout_annot}[kind]
                    na = fn(quads=rest)
                    if na is not None:
                        na.set_colors(stroke=colors.get("stroke") or self.colors[kind])
                        if opacity is not None and 0 <= opacity < 1:
                            na.set_opacity(opacity)
                        na.update()
                pages.append(i)
        self._touch(pages)
        self.sel = None
        self.viewport().update()
        return len(plans)

    def delete_annot_xref(self, i, xref):
        page = self.doc[i]
        a = page.load_annot(xref)
        if a is not None:
            self.delete_annot(page, a)

    def edit_note_xref(self, i, xref):
        page = self.doc[i]
        a = page.load_annot(xref)
        if a is not None:
            self.edit_note(a)

    def edit_note(self, annot):
        text, ok = QInputDialog.getMultiLineText(self, "Note", "Edit note:",
                                                 annot.info.get("content", ""))
        if ok:
            page = annot.parent                 # keep the page alive while editing
            with self.op("Edit note"):
                annot.set_info(content=text)
                annot.update()
            self._touch([page.number])

    def _click(self, pos):
        if self.tool in ("hand", "select"):
            l = self.link_at(pos)
            if l is not None:
                self.follow_link(l)
                return
        page, a = self.annot_under(pos)
        if a is not None and a.type[1] == "Text":
            self.edit_note(a)
        elif a is not None and a.type[1] == "FreeText":
            self.edit_textbox(page, a)

    # ---------------------------------------------------------------- links
    def links(self, i):
        l = self.links_cache.get(i)
        if l is None:
            try:
                l = self.doc[i].get_links()
            except Exception:
                l = []
            self.links_cache[i] = l
        return l

    def link_at(self, pos):
        if self.doc is None or not self.sizes:
            return None
        i, x, y = self._locate(pos.x(), pos.y())
        w, h = self.sizes[i]
        if not (0 <= x <= w and 0 <= y <= h):
            return None
        pt = pymupdf.Point(x, y)
        for l in self.links(i):
            r = l.get("from")
            if r is not None and pt in r:
                return l
        return None

    def _set_cursor(self, shape):
        if shape != self._cur_shape:
            self._cur_shape = shape
            self.viewport().setCursor(shape)

    def _hover_highlight(self, pos):
        """Highlight tool: I-beam over text, cross-hair where a rectangle will be drawn, resize
        cursors on the adjustable rectangle."""
        if self.rect_sel is not None:
            hit = self._rect_hit(pos)
            if hit in ("ok", "cancel"):
                self._set_cursor(Qt.CursorShape.PointingHandCursor)
                return
            if hit == "inside":
                self._set_cursor(Qt.CursorShape.SizeAllCursor)
                return
            if hit in HANDLE_CURSORS:
                self._set_cursor(HANDLE_CURSORS[hit])
                return
        i, x, y = self._locate(pos.x(), pos.y())
        mode = self._highlight_mode_at(i, x, y, QApplication.keyboardModifiers())
        self._set_cursor(Qt.CursorShape.IBeamCursor if mode == "text" else Qt.CursorShape.CrossCursor)

    def _hover(self, pos):
        if self.doc is not None and self.sizes and self.tool == "highlight":
            self._hover_highlight(pos)
            return
        if self.doc is None or self.tool not in ("hand", "select"):
            return
        over = self.link_at(pos) is not None
        if over != self._over_link:
            self._over_link = over
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over
                                      else CURSORS[self.tool])

    def jump_to(self, page, y=None):
        """Go to a page (optionally to a y offset in points), remembering where we were."""
        if self.page_pos == {}:
            return
        self.nav_stack.append((self.horizontalScrollBar().value(), self.verticalScrollBar().value()))
        del self.nav_stack[:-50]
        page = max(0, min(self.page_count - 1, page))
        if y is None:
            self.goto_page(page)
        else:
            top = self.page_pos[page][1] + max(0.0, y) * self.zoom
            self.verticalScrollBar().setValue(int(top - 40))

    def nav_back(self):
        if self.nav_stack:
            hv, vv = self.nav_stack.pop()
            self.horizontalScrollBar().setValue(hv)
            self.verticalScrollBar().setValue(vv)

    def follow_link(self, l):
        kind = l.get("kind")
        if kind == pymupdf.LINK_GOTO:
            pg = l.get("page", -1)
            if pg is not None and 0 <= pg < self.page_count:
                to = l.get("to")
                self.jump_to(pg, to.y if to is not None else None)
        elif kind == pymupdf.LINK_URI:
            uri = l.get("uri", "") or ""
            if uri.lower().startswith(("http://", "https://", "mailto:", "ftp://")):
                QDesktopServices.openUrl(QUrl(uri))
            else:
                QMessageBox.information(self, "Link", "External link:\n%s" % uri)
        elif kind == pymupdf.LINK_NAMED:
            nd = l.get("nameddest")
            if nd:                                    # named destination (very common in LaTeX PDFs)
                try:
                    loc = self.doc.resolve_link("#" + nd)
                except Exception:
                    loc = None
                if loc and loc[0] is not None and 0 <= loc[0] < self.page_count:
                    self.jump_to(loc[0], loc[2])
                return
            cur = self.current_page()               # named action (NextPage, ...)
            target = {"NextPage": cur + 1, "PrevPage": cur - 1, "FirstPage": 0,
                      "LastPage": self.page_count - 1}.get(l.get("name", ""))
            if target is not None:
                self.jump_to(target)
        else:
            QMessageBox.information(self, "Link", "This link type is not supported.")

    # --------------------------------------------------------------- search
    def start_search(self, text):
        self.clear_search(emit=False)
        text = (text or "").strip()
        if self.doc is None or not text:
            self.search_changed.emit()
            return
        self.search_text = text
        self.searching = True
        self._s_page = 0
        self._s_from = self.current_page()
        self._s_pending = True
        self.search_timer.start()
        self.search_changed.emit()

    def clear_search(self, emit=True):
        self.search_timer.stop()
        self.search_text = ""
        self.hits, self.hit_map, self.hit_idx = [], {}, -1
        self.searching = False
        self._s_pending = False
        self.viewport().update()
        if emit:
            self.search_changed.emit()

    def _search_step(self):
        if self.doc is None or not self.searching:
            self.search_timer.stop()
            return
        t0 = time.monotonic()
        n = self.page_count
        while self._s_page < n and time.monotonic() - t0 < 0.03:
            i = self._s_page
            self._s_page += 1
            try:
                rects = self.doc[i].search_for(self.search_text)
            except Exception:
                rects = []
            for r in rects:
                if len(self.hits) >= 20000:
                    break
                self.hit_map.setdefault(i, []).append((len(self.hits), r))
                self.hits.append((i, r))
            if self._s_pending and self.hits and i >= self._s_from:
                k = next((k for k, h in enumerate(self.hits) if h[0] >= self._s_from), None)
                if k is not None:
                    self.hit_idx = k
                    self._s_pending = False
                    self._show_hit()
        if self._s_page >= n:
            self.search_timer.stop()
            self.searching = False
            if self._s_pending and self.hits:
                self.hit_idx = 0
                self._s_pending = False
                self._show_hit()
        self.viewport().update()
        self.search_changed.emit()

    def find_step(self, d):
        if not self.hits:
            return
        self.hit_idx = (self.hit_idx + d) % len(self.hits)
        self._show_hit()
        self.viewport().update()
        self.search_changed.emit()

    def _show_hit(self):
        page, r = self.hits[self.hit_idx]
        z = self.zoom
        x0, y0 = self.page_pos[page]
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        vh, vw = self.viewport().height(), self.viewport().width()
        top, bottom = y0 + r.y0 * z, y0 + r.y1 * z
        if top - vs.value() < 30 or bottom - vs.value() > vh - 30:
            vs.setValue(int(top - vh / 3))
        left, right = x0 + r.x0 * z + self._x_off(), x0 + r.x1 * z + self._x_off()
        if left - hs.value() < 30 or right - hs.value() > vw - 30:
            hs.setValue(int(left - vw / 3))

    # ----------------------------------------------------------- rendering
    def _qimage(self, pix):
        return QImage(pix.samples, pix.width, pix.height, pix.stride,
                      QImage.Format.Format_RGB888).copy()

    def _paint_page(self, p, i, x, y, w, h):
        dpr = self.devicePixelRatioF()
        z = self.zoom
        p.fillRect(QRectF(x, y, w, h), QColor(0x18, 0x18, 0x18) if self.invert_pages else QColor("white"))
        if w * dpr * h * dpr <= FULL_RENDER_LIMIT:
            key = (i, round(z, 4), dpr, self.invert_pages)
            img = self.cache.get(key)
            if img is not None:
                self.cache.move_to_end(key)
                p.drawImage(QRectF(x, y, w, h), img)
                return
            # not rendered yet: show the best stand-in now, the sharp page follows in the background
            self._need = True
            if i in self.last:
                p.drawImage(QRectF(x, y, w, h), self.last[i][1])
            elif i in self.low:
                p.drawImage(QRectF(x, y, w, h), self.low[i])
            else:
                p.setPen(QColor(150, 150, 150))
                p.drawText(QRectF(x, y, w, h), int(Qt.AlignmentFlag.AlignCenter), str(i + 1))
        else:
            if self._fast or (time.monotonic() - self._last_scroll) < 0.12:
                return                      # huge zoom: draw while scrolling pauses (settle repaints)
            vw, vh = self.viewport().width(), self.viewport().height()
            l, t = max(0.0, -x) / z, max(0.0, -y) / z
            r, b = min(w, vw - x) / z, min(h, vh - y) / z
            if r <= l or b <= t:
                return
            pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(z * dpr, z * dpr),
                                         clip=pymupdf.Rect(l, t, r, b), alpha=False)
            part = self._qimage(pix)
            if self.invert_pages:
                part.invertPixels()
            p.drawImage(QRectF(x + l * z, y + t * z, pix.width / dpr, pix.height / dpr), part)

    def _paint_overlays(self, p, i, x, y):
        z = self.zoom
        for r in self.sel_rects(i):
            p.fillRect(QRectF(x + r.x0 * z, y + r.y0 * z, r.width * z, r.height * z),
                       QColor(40, 110, 255, 90))
        for k, r in self.hit_map.get(i, ()):
            cur = k == self.hit_idx
            p.fillRect(QRectF(x + r.x0 * z, y + r.y0 * z, r.width * z, r.height * z),
                       QColor(255, 140, 0, 150) if cur else QColor(255, 235, 0, 110))
        d, rs = self._rect_drag, self.rect_sel
        rect, live = None, False
        if d is not None and d["kind"] in ("new", "newtext") and d["page"] == i:
            rect = d["rect"]
        elif rs is not None and rs["page"] == i:
            rect, live = rs["rect"], True
        if rect is not None and rect.width > 0 and rect.height > 0:
            qr = QRectF(x + rect.x0 * z, y + rect.y0 * z, rect.width * z, rect.height * z)
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(qcolor(self.colors["highlight"], 70) if self.tool == "highlight" else Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(30, 30, 30), 1.2, Qt.PenStyle.DashLine))
            p.drawRect(qr)
            if live:
                p.setPen(QPen(QColor(30, 30, 30), 1))
                p.setBrush(QColor("white"))
                for c in self._handle_points(qr).values():
                    p.drawRect(QRectF(c.x() - 3.5, c.y() - 3.5, 7, 7))
                ok, cancel = self._rect_buttons(qr)
                for b, col, sym in ((ok, QColor(46, 160, 67), "\u2714"), (cancel, QColor(200, 50, 50), "\u2715")):
                    p.setPen(QPen(QColor(255, 255, 255), 1))
                    p.setBrush(col)
                    p.drawRoundedRect(b, 4, 4)
                    p.drawText(b, int(Qt.AlignmentFlag.AlignCenter), sym)
            p.restore()
        if self._stroke is not None and self._stroke_page == i:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(qcolor(self.colors["pen"]), max(1.0, 1.8 * z)))
            pts = self._stroke
            for a, b in zip(pts, pts[1:]):
                p.drawLine(QPointF(x + a[0] * z, y + a[1] * z), QPointF(x + b[0] * z, y + b[1] * z))

    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(0x2a, 0x2a, 0x2c) if self.dark else QColor(0x80, 0x80, 0x80))
        if self.doc is None:
            p.setPen(QColor("white"))
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       "Ctrl+O to open a PDF, or drop a file here")
            return
        hs, vs = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        vh, xo, z = self.viewport().height(), self._x_off(), self.zoom
        self._need = False
        for r in range(max(0, bisect_right(self.row_tops, vs) - 1), len(self.rows)):
            top = self.row_tops[r] - vs
            if top > vh:
                break
            if top + self.row_hs[r] < 0:
                continue
            for i in self.rows[r]:
                if i < 0:
                    continue
                px, py = self.page_pos[i]
                x, y = xo + px - hs, py - vs
                self._paint_page(p, i, x, y, self.sizes[i][0] * z, self.sizes[i][1] * z)
                self._paint_overlays(p, i, x, y)
        if self._need:
            self._schedule_render(30 if (time.monotonic() - self._last_scroll) < 0.12 else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.home is not None and self.doc is None:
            self.home.setGeometry(self.viewport().rect())
        if self.fit:
            self._apply_fit()
        else:
            self._relayout()

    # --------------------------------------------------------------- input
    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        right = bool(ev.buttons() & Qt.MouseButton.RightButton)
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if right or ctrl:
            if right:
                self._right_zoomed = True
            if delta and self.doc is not None:
                pos = ev_pos(ev)
                if self.wheel_down_in:
                    delta = -delta
                self.zoom_by((1 + self.zoom_pct / 100.0) ** (delta / 120.0), (pos.x(), pos.y()))
            ev.accept()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            hs = self.horizontalScrollBar()
            hs.setValue(hs.value() - delta // 2)
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.MouseButton.RightButton:
            self._right_zoomed = False
            return
        if ev.button() != Qt.MouseButton.LeftButton or self.doc is None or not self.sizes:
            return
        pos = ev_pos(ev)
        self._press, self._moved = pos, False
        t = self.tool
        if t == "hand":
            self._pan = pos
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        elif t == "highlight":
            self._press_highlight(pos, ev.modifiers())
        elif t == "textbox":
            i, x, y = self._locate(pos.x(), pos.y())
            self._rect_drag = {"kind": "newtext", "page": i, "p0": (x, y), "rect": pymupdf.Rect(x, y, x, y)}
            self.viewport().update()
        elif t == "select" or t in MARKUP:
            i, x, y = self._locate(pos.x(), pos.y())
            k = self.word_at(i, x, y)
            self.sel = None if k is None else ((i, k), (i, k))
            self._selecting = k is not None
            self.viewport().update()
        elif t == "pen":
            i, x, y = self._locate(pos.x(), pos.y())
            self._stroke, self._stroke_page = [(x, y)], i
        elif t == "note":
            if self._need_pdf():
                i, x, y = self._locate(pos.x(), pos.y())
                text, ok = QInputDialog.getMultiLineText(self, "Note", "Note text:")
                if ok and text.strip():
                    self.add_note(i, x, y, text)
        elif t == "erase":
            page, a = self.annot_under(pos)
            if a is not None:
                self.delete_annot(page, a)

    def mouseMoveEvent(self, ev):
        pos = ev_pos(ev)
        if self._press is None:
            self._hover(pos)
            return
        if self._press is not None and (pos - self._press).manhattanLength() > 3:
            self._moved = True
        if self._rect_drag is not None:
            self._drag_rect(pos)
            self.viewport().update()
        elif self._pan is not None:
            d = pos - self._pan
            self._pan = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
        elif self._selecting and self.sel:
            i, x, y = self._locate(pos.x(), pos.y())
            k = self.word_at(i, x, y)
            if k is not None:
                self.sel = (self.sel[0], (i, k))
                self.viewport().update()
        elif self._stroke is not None:
            i, x, y = self._locate(pos.x(), pos.y())
            if i == self._stroke_page:
                self._stroke.append((x, y))
                self.viewport().update()

    def mouseReleaseEvent(self, ev):
        pos = ev_pos(ev)
        if ev.button() == Qt.MouseButton.LeftButton:
            if self._rect_drag is not None:
                self._finish_rect_drag()
            elif self._pan is not None:
                self._pan = None
                self.viewport().setCursor(CURSORS["hand"])
                if not self._moved:
                    self._click(pos)
            elif self._selecting:
                self._selecting = False
                if not self._moved:
                    self.sel = None
                    self._click(pos)
                elif self.tool in MARKUP:
                    self.markup_selection(self.tool)
            elif self.tool == "highlight" and not self._moved:
                self._click(pos)
            elif self._stroke is not None:
                self._finish_stroke()
            elif self._press is not None and self.tool == "select":
                self._click(pos)
            self._press = None
            self.viewport().update()
        elif ev.button() == Qt.MouseButton.RightButton:
            if not self._right_zoomed and self.menu_factory:
                menu = self.menu_factory(self, pos)
                run_exec(menu, ev_global(ev))
                menu.deleteLater()
            self._right_zoomed = False

    def keyPressEvent(self, ev):
        k, mod = ev.key(), ev.modifiers()
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        K = Qt.Key
        if k == K.Key_PageDown or (k == K.Key_Space and not mod):
            vs.setValue(vs.value() + int(self.viewport().height() * 0.9))
        elif k == K.Key_PageUp or (k == K.Key_Space and mod & Qt.KeyboardModifier.ShiftModifier):
            vs.setValue(vs.value() - int(self.viewport().height() * 0.9))
        elif k == K.Key_Down:
            vs.setValue(vs.value() + 60)
        elif k == K.Key_Up:
            vs.setValue(vs.value() - 60)
        elif k in (K.Key_Right, K.Key_Left):
            sign = 1 if k == K.Key_Right else -1
            if hs.maximum() > 0:
                hs.setValue(hs.value() + 60 * sign)
            else:
                self.goto_row_offset(sign)
        elif k == K.Key_Home:
            self.goto_page(0)
        elif k == K.Key_End:
            self.goto_page(self.page_count - 1)
        elif k in (K.Key_Return, K.Key_Enter) and self.rect_sel is not None:
            self.apply_rect_highlight()
        elif k == K.Key_Escape:
            self.sel = None
            self.cancel_rect()
        else:
            super().keyPressEvent(ev)


class BookmarkStore:
    """Per-file user bookmarks, kept in ~/.config/sumatra-linux/bookmarks.json"""

    _shared = None

    @classmethod
    def shared(cls):
        """One instance for all windows (two windows must not overwrite each other's data)."""
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self):
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        self.file = os.path.join(base, "sumatra-linux", "bookmarks.json")
        try:
            with open(self.file, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def get(self, path):
        return [dict(b) for b in self.data.get(os.path.realpath(path), [])]

    def put(self, path, items):
        key = os.path.realpath(path)
        if items:
            self.data[key] = items
        else:
            self.data.pop(key, None)
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.file)
        except Exception:
            pass


class MarkList(QListWidget):
    delete_requested = pyqtSignal()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
        else:
            super().keyPressEvent(ev)


class ThumbView(QAbstractScrollArea):
    """Page thumbnails. Only the visible cells are drawn and thumbnails are rendered one at a time
    in the background, so even a thousand-page scan neither freezes nor needs seconds to build."""
    page_clicked = pyqtSignal(int)
    TW, TH = 120, 160
    CELL_H = TH + 36

    def __init__(self):
        super().__init__()
        self.n = 0
        self.cur = -1
        self.pix = OrderedDict()
        self.render_fn = None
        self._last_scroll = 0.0
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(self.CELL_H // 2)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_step)

    def count(self):
        return self.n

    def set_count(self, n, render_fn):
        self.n, self.render_fn, self.cur = n, render_fn, -1
        self.pix.clear()
        self._update_range()
        self.verticalScrollBar().setValue(0)
        self.viewport().update()
        self._sched()

    def _update_range(self):
        vh = self.viewport().height()
        vs = self.verticalScrollBar()
        vs.setRange(0, max(0, self.n * self.CELL_H - vh))
        vs.setPageStep(vh)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_range()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sched()

    def _visible(self, extra=0):
        vs, vh = self.verticalScrollBar().value(), self.viewport().height()
        return range(max(0, vs // self.CELL_H - extra), min(self.n, (vs + vh) // self.CELL_H + 1 + extra))

    def _scrolled(self, *a):
        self._last_scroll = time.monotonic()
        self.viewport().update()
        self._sched()

    def _sched(self):
        if not self._timer.isActive():
            self._timer.start(110 if (time.monotonic() - self._last_scroll) < 0.15 else 4)

    def _render_step(self):
        if self.render_fn is None or not self.isVisible():
            return
        if (time.monotonic() - self._last_scroll) < 0.1:          # still scrolling: wait
            self._sched()
            return
        vs, vh = self.verticalScrollBar().value(), self.viewport().height()
        mid = (vs + vh / 2) / self.CELL_H
        for i in sorted(self._visible(2), key=lambda k: abs(k + 0.5 - mid)):
            if i in self.pix:
                continue
            try:
                pm = self.render_fn(i)
            except Exception:
                pm = None
            self.pix[i] = pm if pm is not None else QPixmap()
            while len(self.pix) > 400:
                self.pix.popitem(last=False)
            self.viewport().update()
            self._sched()
            return

    def invalidate(self, i):
        if i in self.pix:
            del self.pix[i]
            self.viewport().update()
            self._sched()

    def select_page(self, page):
        if page == self.cur:
            return
        self.cur = page
        if page >= 0 and page not in self._visible():
            vh = self.viewport().height()
            self.verticalScrollBar().setValue(max(0, page * self.CELL_H - (vh - self.CELL_H) // 2))
        self.viewport().update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            i = (self.verticalScrollBar().value() + ev_pos(ev).y()) // self.CELL_H
            if 0 <= i < self.n:
                self.page_clicked.emit(int(i))

    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        pal = self.palette()
        base = pal.color(QPalette.ColorRole.Base)
        p.fillRect(self.viewport().rect(), base)
        vs, vw = self.verticalScrollBar().value(), self.viewport().width()
        for i in self._visible():
            top = i * self.CELL_H - vs
            if i == self.cur:
                hl = QColor(pal.color(QPalette.ColorRole.Highlight))
                hl.setAlpha(90)
                p.fillRect(QRect(3, top + 2, vw - 6, self.CELL_H - 4), hl)
            pm = self.pix.get(i)
            if pm is not None and not pm.isNull():
                p.drawPixmap((vw - pm.width()) // 2, top + 4, pm)
            else:
                box = QRect((vw - self.TW) // 2, top + 4, self.TW, self.TH)
                p.fillRect(box, QColor(60, 60, 64) if base.lightness() < 100 else QColor(245, 245, 245))
                p.setPen(QColor(150, 150, 150))
                p.drawRect(box.adjusted(0, 0, -1, -1))
            p.setPen(pal.color(QPalette.ColorRole.Text))
            p.drawText(QRect(0, top + 4 + self.TH + 2, vw, 26), int(Qt.AlignmentFlag.AlignCenter), str(i + 1))


class Dock(QDockWidget):
    closed = pyqtSignal()
    resized = pyqtSignal()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.resized.emit()

    def closeEvent(self, ev):
        super().closeEvent(ev)
        self.closed.emit()


class Sidebar(QObject):
    """Controller for three independent panels: outline, thumbnails, bookmarks."""
    TW, TH = 120, 160

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.view = None
        self.has_toc = False
        self.mark_thumbs = True
        UR = Qt.ItemDataRole.UserRole
        self.UR = UR

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda it, col=0: self._goto(it.data(0, UR)))

        self.thumbs = ThumbView()
        self.thumbs.page_clicked.connect(self._goto)

        self.marks = MarkList()
        self.marks.itemClicked.connect(lambda it: self._goto(it.data(UR)))
        self.marks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.marks.customContextMenuRequested.connect(self._marks_menu)
        self.marks.delete_requested.connect(self._delete_selected)

        self._mark_queue = []
        self._mark_gen = 0

    def set_mark_thumbs(self, on):
        self.mark_thumbs = on
        self._refresh_marks()

    def _goto(self, page):
        if self.view is not None and page is not None:
            self.view.jump_to(int(page))
            self.view.setFocus()

    # ------------------------------------------------------------- content
    def set_view(self, v, fresh=False):
        self.view = v
        self.tree.clear()
        self.thumbs.set_count(0, None)
        self.has_toc = False
        if v is None or v.doc is None:
            self.marks.clear()
            return
        try:
            toc = v.doc.get_toc(simple=True)
        except Exception:
            toc = []
        self.has_toc = bool(toc)
        stack = [(0, self.tree.invisibleRootItem())]
        for lvl, title, page in toc:
            while len(stack) > 1 and stack[-1][0] >= lvl:
                stack.pop()
            it = QTreeWidgetItem(stack[-1][1], [(title or "").strip() or "(untitled)"])
            it.setData(0, self.UR, page - 1 if page > 0 else None)
            stack.append((lvl, it))
        if not toc:
            it = QTreeWidgetItem(self.tree, ["(no outline in this document)"])
            it.setDisabled(True)
        else:
            self.tree.expandToDepth(0)
        self.thumbs.set_count(v.page_count, self._thumb_pix)
        self._refresh_marks()
        self.select_page(v.current_page())

    def select_page(self, page):
        self.thumbs.select_page(page)

    # ----------------------------------------------------------- thumbnails
    @property
    def _loaded(self):
        return {k for k, pm in self.thumbs.pix.items() if not pm.isNull()}

    def _thumb_pix(self, i):
        """Thumbnail of page i as a QPixmap with a thin border (None if it cannot be rendered)."""
        v = self.view
        if v is None or v.doc is None or not (0 <= i < v.page_count):
            return None
        page = v.doc[i]
        r = page.rect
        z = min(self.TW / max(r.width, 1), self.TH / max(r.height, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        del page
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        pp = QPainter(pm)
        pp.setPen(QColor(150, 150, 150))
        pp.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        pp.end()
        return pm

    def refresh_thumb(self, i):
        self.thumbs.invalidate(i)
        for r in range(self.marks.count()):               # bookmark thumbnails follow annotation changes
            it = self.marks.item(r)
            if self.mark_thumbs and it is not None and it.data(self.UR) == i:
                self._mark_queue.append(r)
        if self._mark_queue:
            QTimer.singleShot(60, self._mark_icon_step)

    # ------------------------------------------------------------ bookmarks
    def _items(self):
        v = self.view
        return self.store.get(v.path) if v is not None and v.path else []

    def _refresh_marks(self):
        self.marks.clear()
        self._mark_gen += 1
        self._mark_queue = []
        use = self.mark_thumbs and self.view is not None and self.view.doc is not None
        if use:
            self.marks.setViewMode(QListView.ViewMode.IconMode)
            self.marks.setFlow(QListView.Flow.TopToBottom)
            self.marks.setWrapping(False)
            self.marks.setMovement(QListView.Movement.Static)
            self.marks.setResizeMode(QListView.ResizeMode.Adjust)
            self.marks.setIconSize(QSize(self.TW, self.TH))
            self.marks.setGridSize(QSize(self.TW + 90, self.TH + 64))
            self.marks.setWordWrap(True)
            ph = QPixmap(self.TW, self.TH)
            ph.fill(QColor(245, 245, 245))
            pp = QPainter(ph)
            pp.setPen(QColor(150, 150, 150))
            pp.drawRect(0, 0, self.TW - 1, self.TH - 1)
            pp.end()
            ph_icon = QIcon(ph)
        else:
            self.marks.setViewMode(QListView.ViewMode.ListMode)
            self.marks.setFlow(QListView.Flow.TopToBottom)
            self.marks.setWrapping(False)
            self.marks.setIconSize(QSize(16, 16))
            self.marks.setGridSize(QSize(-1, -1))
            self.marks.setWordWrap(False)
        for b in self._items():
            if use:
                it = QListWidgetItem(ph_icon, "%s\n(p. %d)" % (b["label"], b["page"] + 1))
            else:
                it = QListWidgetItem("%s  (p. %d)" % (b["label"], b["page"] + 1))
            it.setData(self.UR, b["page"])
            self.marks.addItem(it)
        if use and self.marks.count():
            self._mark_queue = list(range(self.marks.count()))
            QTimer.singleShot(20, self._mark_icon_step)

    def _mark_icon_step(self):
        """Fill the bookmark thumbnails one by one (never blocks the window)."""
        if not self._mark_queue or not self.mark_thumbs:
            return
        gen = self._mark_gen
        r = self._mark_queue.pop(0)
        it = self.marks.item(r)
        if it is not None:
            page = it.data(self.UR)
            try:
                pm = self.thumbs.pix.get(page)
                if pm is None or pm.isNull():
                    pm = self._thumb_pix(page)
                if pm is not None and gen == self._mark_gen:
                    it.setIcon(QIcon(pm))
            except Exception:
                pass
        if self._mark_queue and gen == self._mark_gen:
            QTimer.singleShot(15, self._mark_icon_step)

    def add_bookmark(self):
        v = self.view
        if v is None or v.doc is None or not v.path:
            return
        page = v.current_page()
        default = " ".join(w[4] for w in v.words(page)[:6]) or "Page %d" % (page + 1)
        label, ok = QInputDialog.getText(self.marks, "Add bookmark", "Name (page %d):" % (page + 1),
                                         QLineEdit.EchoMode.Normal, default[:80])
        if not ok:
            return
        items = [b for b in self._items() if b["page"] != page]
        items.append({"page": page, "label": label.strip() or default})
        items.sort(key=lambda b: b["page"])
        self.store.put(v.path, items)
        self._refresh_marks()

    def _marks_menu(self, pos):
        item = self.marks.itemAt(pos)
        if item is None:
            return
        m = QMenu(self.marks)
        m.addAction("Rename…", lambda checked=False: self._rename(item))
        m.addAction("Delete", lambda checked=False: self._delete(item))
        run_exec(m, self.marks.viewport().mapToGlobal(pos))

    def _rename(self, item):
        page = item.data(self.UR)
        items = self._items()
        for b in items:
            if b["page"] == page:
                new, ok = QInputDialog.getText(self.marks, "Rename bookmark", "Name:",
                                               QLineEdit.EchoMode.Normal, b["label"])
                if ok and new.strip():
                    b["label"] = new.strip()
                    self.store.put(self.view.path, items)
                    self._refresh_marks()
                return

    def _delete(self, item):
        page = item.data(self.UR)
        self.store.put(self.view.path, [b for b in self._items() if b["page"] != page])
        self._refresh_marks()

    def _delete_selected(self):
        item = self.marks.currentItem()
        if item is not None:
            self._delete(item)


class RecentStore:
    """Open counts per file (for the start page) + thumbnail cache location."""

    _shared = None

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self):
        cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        self.file = os.path.join(cfg, "sumatra-linux", "recent.json")
        self.thumb_dir = os.path.join(cache, "sumatra-linux", "thumbs")
        try:
            with open(self.file, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}
        self.data.setdefault("hide", False)
        self.data.setdefault("docs", {})
        self.data.setdefault("modes", {})
        self.data.setdefault("panels", {})
        self.data.setdefault("widths", {})
        self.data.setdefault("settings", {})
        self.data.setdefault("pins", {})          # pinned books: path -> time pinned

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.file)
        except Exception:
            pass

    def touch(self, path, bump=True):
        """Record that a file was opened (bump=False: only refresh its 'recent' time)."""
        d = self.data["docs"].setdefault(os.path.realpath(path), {"n": 0, "t": 0})
        if bump:
            d["n"] += 1
        d["t"] = time.time()
        self._save()

    def remove(self, path):
        self.data["docs"].pop(path, None)
        self.data["pins"].pop(path, None)
        self._save()

    def recent(self, n=10):
        """Most recently opened files (newest first); files that no longer exist are skipped."""
        items = [(k, v) for k, v in self.data["docs"].items() if os.path.isfile(k)]
        items.sort(key=lambda kv: -kv[1].get("t", 0))
        return [k for k, _ in items[:n]]

    def clear(self):
        self.data["docs"] = {}
        self._save()

    PANELS = ("outline", "thumbs", "marks")

    def get_width(self, path):
        """Remembered side-panel width (px) for this file, or None."""
        w = self.data["widths"].get(os.path.realpath(path))
        return int(w) if isinstance(w, (int, float)) and w > 0 else None

    def set_width(self, path, w):
        self.data["widths"][os.path.realpath(path)] = int(w)
        self._save()

    SETTING_DEFAULTS = {"wheel_down_in": True, "dark": False, "dark_pages": True,
                        "mark_thumbs": True, "hl_mode": "auto", "open_mode": "tabs",
                        "color_highlight": "Yellow", "color_underline": "Yellow",
                        "color_strike": "Yellow", "color_pen": "Yellow",
                        "home_sort": "recent"}

    def setting(self, name):
        return self.data["settings"].get(name, self.SETTING_DEFAULTS[name])

    def set_setting(self, name, value):
        self.data["settings"][name] = value
        self._save()

    @property
    def zoom_step(self):
        try:
            return max(2, min(100, int(self.data.get("zoom_step", 10))))
        except (TypeError, ValueError):
            return 10

    @zoom_step.setter
    def zoom_step(self, v):
        self.data["zoom_step"] = max(2, min(100, int(v)))
        self._save()

    def get_panels(self, path):
        """Which side panels are open for this file (default: all three)."""
        st = self.data["panels"].get(os.path.realpath(path), {})
        return {k: bool(st.get(k, True)) for k in self.PANELS}

    def set_panels(self, path, state):
        key = os.path.realpath(path)
        if all(state.get(k, True) for k in self.PANELS):
            self.data["panels"].pop(key, None)          # default -> nothing to remember
        else:
            self.data["panels"][key] = {k: bool(state.get(k, True)) for k in self.PANELS}
        self._save()

    def get_mode(self, path):
        m = self.data["modes"].get(os.path.realpath(path), "single")
        return m if m in ("single", "facing", "book") else "single"

    def set_mode(self, path, mode):
        key = os.path.realpath(path)
        if mode == "single":
            self.data["modes"].pop(key, None)
        else:
            self.data["modes"][key] = mode
        self._save()

    @property
    def hide(self):
        return bool(self.data.get("hide"))

    @hide.setter
    def hide(self, v):
        self.data["hide"] = bool(v)
        self._save()

    LIST_MAX = 10          # recently opened books on the start page - pinned books are not counted

    def is_pinned(self, path):
        return os.path.realpath(path) in self.data["pins"]

    def _ranked(self, exclude=()):
        """Unpinned books: most recently opened first, or (home_sort = frequent) most opened first."""
        pins = self.data["pins"]
        items = [(k, v) for k, v in self.data["docs"].items()
                 if k not in pins and k not in exclude and os.path.isfile(k)]
        if self.setting("home_sort") == "frequent":
            items.sort(key=lambda kv: (-kv[1].get("n", 0), -kv[1].get("t", 0)))
        else:
            items.sort(key=lambda kv: -kv[1].get("t", 0))
        return [k for k, _ in items]

    def set_pinned(self, path, on):
        key = os.path.realpath(path)
        if on:
            self.data["pins"][key] = time.time()
        else:
            self.data["pins"].pop(key, None)
            # an unpinned book joins the list like one that was just opened: it takes the first
            # place and the oldest book of the list drops out
            rest = self._ranked(exclude=(key,))
            d = self.data["docs"].setdefault(key, {"n": 0, "t": 0})
            if self.setting("home_sort") == "frequent" and len(rest) >= self.LIST_MAX:
                d["n"] = max(d.get("n", 0), self.data["docs"][rest[self.LIST_MAX - 1]].get("n", 0))
            d["t"] = time.time()
        self._save()

    def top(self, n=None):
        """Pinned books (in the order they were pinned) + the `n` first other books of the chosen order."""
        n = self.LIST_MAX if n is None else n
        pins = sorted((t, k) for k, t in self.data["pins"].items() if os.path.isfile(k))
        return [k for _, k in pins] + self._ranked()[:n]

    def thumb_path(self, path):
        st = os.stat(path)
        h = hashlib.sha1(("%s|%d|%d" % (path, st.st_mtime_ns, st.st_size)).encode()).hexdigest()
        return os.path.join(self.thumb_dir, h + ".png")


def pin_icon(pinned):
    """A small drawing-pin icon: red when the book is pinned, grey otherwise."""
    pm = QPixmap(24, 24)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(12, 12)
    p.rotate(40)
    p.translate(-12, -12)
    p.setPen(QPen(QColor(60, 60, 60), 1))
    p.setBrush(QColor(205, 40, 40) if pinned else QColor(150, 150, 150))
    p.drawRoundedRect(QRectF(7, 1.5, 10, 9), 3, 3)
    p.drawRect(QRectF(5, 10, 14, 2.5))
    p.setPen(QPen(QColor(70, 70, 70), 1.6))
    p.drawLine(QPointF(12, 12.5), QPointF(12, 22.5))
    p.end()
    return QIcon(pm)


class Card(QWidget):
    """One document on the start page: thumbnail + file name."""
    W, H = 212, 150
    clicked = pyqtSignal()
    remove_requested = pyqtSignal()
    pin_toggled = pyqtSignal()

    def __init__(self, path, pinned=False):
        super().__init__()
        self.path = path
        self.pinned = pinned
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.thumb = QLabel()
        self.thumb.setFixedSize(self.W + 2, self.H + 2)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: white; border: 1px solid #555; color: #888;")
        self.thumb.setText("…")
        self.name = QLabel()
        self.name.setStyleSheet("color: #000;")
        self.dark = False
        self.name.setText(self.name.fontMetrics().elidedText(
            os.path.basename(path), Qt.TextElideMode.ElideRight, self.W - 6))
        self.name.setToolTip(path)
        lay.addWidget(self.thumb)
        lay.addWidget(self.name)
        self.pin = QToolButton(self.thumb)               # pin in the top-right corner of the thumbnail
        self.pin.setFixedSize(26, 26)
        self.pin.setIconSize(QSize(20, 20))
        self.pin.setCursor(Qt.CursorShape.ArrowCursor)
        self.pin.move(self.W + 2 - 26 - 3, 3)
        self.pin.clicked.connect(lambda checked=False: self.pin_toggled.emit())
        self.set_pinned(pinned)
        self.setFixedWidth(self.W + 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_pinned(self, pinned):
        self.pinned = pinned
        self.pin.setIcon(pin_icon(pinned))
        self.pin.setToolTip("Unpin (can be removed from the list again)" if pinned
                            else "Pin (keep this book on the start page)")
        self.pin.setStyleSheet("QToolButton { background: rgba(255,255,255,%d); border: 1px solid %s; "
                               "border-radius: 4px; }" % ((235, "#c82828") if pinned else (170, "#999999")))

    def set_dark(self, dark):
        self.dark = dark
        self.name.setStyleSheet("color: %s;" % ("#dddddd" if dark else "#000000"))
        self.thumb.setStyleSheet("background: %s; border: 1px solid %s; color: #888;" % (
            ("#1e1e1e", "#888") if dark else ("white", "#555")))

    def set_thumb(self, pm):
        if pm is None or pm.isNull():
            self.thumb.setText(os.path.splitext(self.path)[1].upper().lstrip(".") or "FILE")
        else:
            self.thumb.setPixmap(pm)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Unpin" if self.pinned else "Pin book", lambda checked=False: self.pin_toggled.emit())
        m.addAction("Remove from list", lambda checked=False: self.remove_requested.emit())
        run_exec(m, self.mapToGlobal(pos))

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(ev_pos(ev)):
            self.clicked.emit()


class HomePage(QScrollArea):
    """'Frequently Read' start page shown in an empty tab (like SumatraPDF)."""
    open_path = pyqtSignal(str)
    open_dialog = pyqtSignal()
    MAX = 10

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.dark = False
        self.cards = []
        self._paths = None
        self._cols = 0
        self._queue = []
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.inner = QWidget()
        self.inner.setObjectName("home")
        self.inner.setStyleSheet("#home { background: #f2f2f2; } QLabel { color: #000; }")
        self.setWidget(self.inner)
        lay = QVBoxLayout(self.inner)
        lay.setContentsMargins(60, 36, 60, 18)
        lay.setSpacing(20)
        self.title = QLabel("Recently Read")
        f = self.title.font()
        f.setPointSize(18)
        self.title.setFont(f)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(28)
        self.grid.setVerticalSpacing(24)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.open_link = QLabel('<a href="open" style="color:#0000cc">Open a document…</a>')
        self.toggle_link = QLabel()
        self.toggle_link.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.open_link.linkActivated.connect(lambda _=None: self.open_dialog.emit())
        self.toggle_link.linkActivated.connect(lambda _=None: self._toggle())
        lay.addWidget(self.title)
        lay.addWidget(self.grid_host)
        lay.addWidget(self.open_link)
        lay.addStretch(1)
        lay.addWidget(self.toggle_link)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._next_thumb)

    def set_dark(self, dark):
        self.dark = dark
        self.inner.setStyleSheet(
            "#home { background: #2b2b2e; } QLabel { color: #dddddd; }" if dark
            else "#home { background: #f2f2f2; } QLabel { color: #000; }")
        link = "#7fb2ff" if dark else "#0000cc"
        self.open_link.setText('<a href="open" style="color:%s">Open a document…</a>' % link)
        self._paths = None
        for c in self.cards:
            c.set_dark(dark)
        if self.isVisible():
            self.refresh()

    def _toggle(self):
        self.store.hide = not self.store.hide
        self._paths = None
        self.refresh()

    def refresh(self):
        hide = self.store.hide
        paths = [] if hide else self.store.top(self.MAX)
        mode = self.store.setting("home_sort")
        what = "frequently read" if mode == "frequent" else "recently read"
        self.title.setText(what.title())
        key = (hide, mode, tuple((p, self.store.is_pinned(p)) for p in paths))
        if key == self._paths:
            return
        self._paths = key
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        for pth in paths:
            c = Card(pth, self.store.is_pinned(pth))
            c.set_dark(self.dark)
            c.pin_toggled.connect(lambda pth=pth: self._toggle_pin(pth))
            c.clicked.connect(lambda pth=pth: self.open_path.emit(pth))
            c.remove_requested.connect(lambda pth=pth: self._remove(pth))
            self.cards.append(c)
        self.title.setVisible(bool(paths))
        self.grid_host.setVisible(bool(paths))
        have_any = bool(self.store.data["docs"])
        self.toggle_link.setVisible(have_any)
        self.toggle_link.setText('<a href="t" style="color:%s">%s</a>' % (
            "#7fb2ff" if self.dark else "#0000cc",
            "Show " + what if hide else "Hide " + what))
        self._cols = 0
        self._relayout()
        self._queue = list(self.cards)
        self._timer.start()

    def _toggle_pin(self, path):
        self.store.set_pinned(path, not self.store.is_pinned(path))
        self._paths = None
        self.refresh()

    def _remove(self, path):
        self.store.remove(path)
        self._paths = None
        self.refresh()

    def _relayout(self):
        cols = max(1, (self.viewport().width() - 120) // (Card.W + 2 + 28))
        if cols == self._cols:
            return
        self._cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()
        if self._queue:
            self._timer.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._timer.stop()

    def _next_thumb(self):
        if not self._queue:
            return
        card = self._queue.pop(0)
        try:
            card.set_thumb(self._thumb_for(card.path))
        except RuntimeError:           # card was deleted meanwhile
            pass
        if self._queue:
            self._timer.start()

    def _thumb_for(self, path):
        try:
            cache = self.store.thumb_path(path)
        except OSError:
            return None
        if os.path.isfile(cache):
            pm = QPixmap(cache)
            if not pm.isNull():
                return pm
        img = self._render(path)
        if img is None:
            return None
        try:
            os.makedirs(self.store.thumb_dir, exist_ok=True)
            img.save(cache, "PNG")
        except Exception:
            pass
        return QPixmap.fromImage(img)

    def _render(self, path):
        """First page, scaled to the card width and cropped to the card height."""
        try:
            doc = pymupdf.open(path)
            try:
                if doc.needs_pass or doc.page_count == 0:
                    return None
                page = doc[0]
                z = Card.W / max(page.rect.width, 1)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
                src = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888).copy()
            finally:
                doc.close()
        except Exception:
            return None
        out = QImage(Card.W, Card.H, QImage.Format.Format_RGB32)
        out.fill(QColor("white"))
        p = QPainter(out)
        p.drawImage(0, 0, src, 0, 0, Card.W, min(src.height(), Card.H))
        p.end()
        return out


class AskBox(QMessageBox):
    """Yes/No message box where Esc or the window's close button simply cancels."""

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.done(0)
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        ev.accept()
        self.done(0)


class FindEdit(QLineEdit):
    escape = pyqtSignal()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(ev)


class MainWindow(QMainWindow):
    instances = []                 # every open window (window mode opens each PDF in its own)
    _orig_style = None             # the desktop's own style / palette, kept for leaving dark mode
    _orig_palette = None

    def __init__(self):
        super().__init__()
        MainWindow.instances.append(self)
        self.tool = "hand"
        if MainWindow._orig_style is None:
            MainWindow._orig_style = QApplication.style().objectName()
            MainWindow._orig_palette = QPalette(QApplication.palette())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self.store = BookmarkStore.shared()
        self.recent = RecentStore.shared()
        self.sidebar = Sidebar(self.store)
        self.docks = {}
        for key, title, widget in (("outline", "Outline", self.sidebar.tree),
                                   ("thumbs", "Thumbnails", self.sidebar.thumbs),
                                   ("marks", "Bookmarks", self.sidebar.marks)):
            d = Dock(title, self)
            d.setWidget(widget)
            d.setObjectName("dock_" + key)
            d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                          | QDockWidget.DockWidgetFeature.DockWidgetMovable)
            d.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
            d.setMinimumWidth(200)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, d)
            self.docks[key] = d
        self.tabifyDockWidget(self.docks["outline"], self.docks["thumbs"])
        self.tabifyDockWidget(self.docks["thumbs"], self.docks["marks"])
        self.docks["outline"].raise_()
        self.setTabPosition(Qt.DockWidgetArea.LeftDockWidgetArea, QTabWidget.TabPosition.North)
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        self._side_key = None
        self._applying_w = False
        self._side_base = None
        self._side_timer = QTimer(self)
        self._side_timer.setSingleShot(True)
        self._side_timer.setInterval(400)
        self._side_timer.timeout.connect(self._side_resized)
        for d in self.docks.values():
            d.resized.connect(lambda: self._side_timer.start())
        self._open_panels = {}
        self._find_was_visible = False
        self.setAcceptDrops(True)
        self.resize(1100, 850)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.sidebar.mark_thumbs = self.recent.setting("mark_thumbs")
        self.new_tab()
        # window mode: one PDF per window, so no tab bar / Tabs button (decided when the window is created)
        self._tabs_chrome = self.recent.setting("open_mode") == "tabs"
        self._apply_tab_chrome()
        if self.recent.setting("dark"):
            self.apply_theme()

    # ------------------------------------------------------------- actions
    def _act(self, text, keys=None, slot=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcuts([QKeySequence(k) for k in keys])
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        self.addAction(a)
        return a

    def view(self):
        return self.tabs.currentWidget()

    def _build_actions(self):
        v = self.view
        self.a_open = self._act("Open…", ["Ctrl+O"], lambda: self.open_dialog())
        self.a_save = self._act("Save", ["Ctrl+S"], lambda: self.save())
        self.a_saveas = self._act("Save as…", ["Ctrl+Shift+S"], lambda: self.save_as())
        self.a_reload = self._act("Reload", ["Ctrl+R", "F5"], lambda: self.reload())
        self.a_closetab = self._act("Close tab", ["Ctrl+W"], lambda: self._close_current())
        self.a_next = self._act("Next tab", ["Ctrl+Tab", "Ctrl+PgDown"], lambda: self._step_tab(1))
        self.a_prev = self._act("Previous tab", ["Ctrl+Shift+Tab", "Ctrl+PgUp"], lambda: self._step_tab(-1))
        self.a_quit = self._act("Quit", ["Ctrl+Q"], lambda: self.close())
        self.a_goto = self._act("Go to page…", ["Ctrl+G"], lambda: self.goto_dialog())
        self.a_copy = self._act("Copy text", ["Ctrl+C"], lambda: v().copy_selection())
        self.a_w = self._act("Fit width", ["Ctrl+3"], lambda: v().fit_width())
        self.a_p = self._act("Fit page", ["Ctrl+2"], lambda: v().fit_page())
        self.a_100 = self._act("Actual size", ["Ctrl+1"], lambda: v().actual_size())
        self.a_zi = self._act("Zoom in", ["Ctrl+=", "Ctrl++"], lambda: v().zoom_by(1.2))
        self.a_zo = self._act("Zoom out", ["Ctrl+-"], lambda: v().zoom_by(1 / 1.2))
        self.a_fs = self._act("Fullscreen", ["F11"], lambda: self.toggle_fullscreen())
        self.panel_actions = {}
        for key, label, sc in (("outline", "Outline", "F6"), ("thumbs", "Thumbnails", "F7"),
                               ("marks", "Bookmarks", "F8")):
            a = self._act(label, [sc], lambda checked=False, k=key: self._set_panel(k, checked), True)
            a.setChecked(True)
            self.panel_actions[key] = a
            self.docks[key].closed.connect(lambda k=key: self._panel_closed(k))
        self.a_print = self._act("Print…", ["Ctrl+P"], lambda: self.print_document())
        self.a_print.setEnabled(QPrinter is not None)
        self.a_refresh = self._act("Refresh", None, lambda: self.reload())
        self.a_refresh.setToolTip("Reload the file from disk (Ctrl+R)")
        self.a_home = self._act("Home", None, lambda: self.go_home())
        self.a_home.setToolTip("Start page (Home overview)")
        self.a_prevpage = self._act("\u2190", None, lambda: self.view().goto_row_offset(-1))
        self.a_prevpage.setToolTip("Previous page")
        self.a_nextpage = self._act("\u2192", None, lambda: self.view().goto_row_offset(1))
        self.a_nextpage.setToolTip("Next page")
        self.a_zin = self._act("+", None, lambda: self.view().zoom_by(1.25))
        self.a_zin.setToolTip("Zoom in")
        self.a_zout = self._act("\u2212", None, lambda: self.view().zoom_by(1 / 1.25))
        self.a_zout.setToolTip("Zoom out")
        self.a_undo = self._act("Undo", ["Ctrl+Z"], lambda: self._undo_redo(-1))
        self.a_redo = self._act("Redo", ["Ctrl+Y", "Ctrl+Shift+Z"], lambda: self._undo_redo(1))
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        self.a_find = self._act("Find…", ["Ctrl+F"], lambda: self.show_find())
        self.a_findnext = self._act("Find next", ["F3"], lambda: self.find_step(1))
        self.a_findprev = self._act("Find previous", ["Shift+F3"], lambda: self.find_step(-1))
        self.a_findclose = self._act("✕ Close", None, lambda: self.close_find())
        self.a_back = self._act("Go back", ["Alt+Left"], lambda: self.view().nav_back())
        self.a_zoomspeed = self._act("Zoom speed…", None, lambda: self.zoom_speed_dialog())
        self.a_about = self._act("About", None, lambda: self.about_dialog())
        self.home_group = QActionGroup(self)
        self.home_actions = {}
        for key, label in (("frequent", "Frequently read"), ("recent", "Recent read")):
            a = self._act(label, None, lambda checked=False, k=key: self._set_home_sort(k), True)
            self.home_group.addAction(a)
            self.home_actions[key] = a
        self.home_actions[self.recent.setting("home_sort")].setChecked(True)
        # ---- Settings
        R = self.recent
        self.wheel_group = QActionGroup(self)
        self.a_wheel_up = self._act("Wheel up = zoom in, wheel down = zoom out  (+/−)", None,
                                    lambda checked=False: self._set_wheel(False), True)
        self.a_wheel_down = self._act("Wheel down = zoom in, wheel up = zoom out  (−/+)  [inverted]", None,
                                      lambda checked=False: self._set_wheel(True), True)
        for a in (self.a_wheel_up, self.a_wheel_down):
            self.wheel_group.addAction(a)
        (self.a_wheel_down if R.setting("wheel_down_in") else self.a_wheel_up).setChecked(True)
        self.a_dark = self._act("Dark mode", None, lambda checked=False: self._set_dark(checked), True)
        self.a_dark.setChecked(R.setting("dark"))
        self.a_darkpages = self._act("Invert page colours in dark mode", None,
                                     lambda checked=False: self._set_dark_pages(checked), True)
        self.a_darkpages.setChecked(R.setting("dark_pages"))
        self.a_markthumbs = self._act("Show bookmarks with thumbnails", None,
                                      lambda checked=False: self._set_mark_thumbs(checked), True)
        self.a_markthumbs.setChecked(R.setting("mark_thumbs"))
        self.hl_group = QActionGroup(self)
        self.hl_actions = {}
        for key, label in (("rect", "Highlight with selection (draw a rectangle)"),
                           ("text", "Highlight with select text"),
                           ("auto", "Automatic (text where there is text, rectangle on images / figures)")):
            a = self._act(label, None, lambda checked=False, k=key: self._set_hl_mode(k), True)
            self.hl_group.addAction(a)
            self.hl_actions[key] = a
        self.hl_actions[R.setting("hl_mode")].setChecked(True)
        self.open_group = QActionGroup(self)
        self.open_actions = {}
        for key, label in (("tabs", "Tab mode: open new PDFs in tabs"),
                           ("window", "Window mode: open each PDF in its own window")):
            a = self._act(label, None, lambda checked=False, k=key: self._set_open_mode(k), True)
            self.open_group.addAction(a)
            self.open_actions[key] = a
        self.open_actions[R.setting("open_mode")].setChecked(True)
        self.a_bookmark = self._act("Add bookmark…", ["Ctrl+D"], lambda: self._add_bookmark())
        self.mode_group = QActionGroup(self)
        self.mode_actions = {}
        for key, label, sc in (("single", "Single page", "Ctrl+6"), ("facing", "Facing (two pages)", "Ctrl+7"),
                               ("book", "Book view", "Ctrl+8")):
            a = self._act(label, [sc], lambda checked=False, k=key: self.set_mode(k), True)
            self.mode_group.addAction(a)
            self.mode_actions[key] = a
        self.mode_actions["single"].setChecked(True)
        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for key, label, sc in TOOLS:
            a = self._act(label, [sc], lambda checked=False, k=key: self.set_tool(k), True)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
        self.tool_actions["hand"].setChecked(True)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        for a in (self.a_save, self.a_saveas, self.a_print, self.a_reload, self.a_closetab):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_quit)
        m = mb.addMenu("&View")
        for a in self.mode_actions.values():
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_w, self.a_p, self.a_100, self.a_zi, self.a_zo, self.a_goto,
                  self.a_back, self.a_bookmark, self.a_fs):
            m.addAction(a)
        m.addSeparator()
        for a in self.panel_actions.values():
            m.addAction(a)
        m = mb.addMenu("&Edit")
        m.aboutToShow.connect(self._sync_color_checks)       # the right-click menu / other windows may have changed them
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addSeparator()
        self.color_actions = {}
        for kind in COLOR_KINDS:
            sub = m.addMenu(KIND_LABELS[kind])
            grp = QActionGroup(self)
            grp.setExclusive(True)
            acts = {}
            for name, rgb in COLORS:
                a = QAction(name, self)
                a.setCheckable(True)
                a.triggered.connect(lambda checked=False, k=kind, n=name: self._set_kind_color(k, n))
                grp.addAction(a)
                sub.addAction(a)
                acts[name] = a
            self.color_actions[kind] = acts
        m.addAction(self.tool_actions["note"])
        m.addAction(self.tool_actions["textbox"])
        m.addSeparator()
        for a in (self.a_find, self.a_findnext, self.a_findprev):
            m.addAction(a)
        self._sync_color_checks()
        self.settings_menu = m = mb.addMenu("&Settings")
        m.aboutToShow.connect(self._sync_settings_checks)     # other windows may have changed them
        sub = m.addMenu("Opening PDFs")
        for a in self.open_actions.values():
            sub.addAction(a)
        m.addSeparator()
        m.addAction(self.a_zoomspeed)
        sub = m.addMenu("Mouse wheel zoom")
        sub.addAction(self.a_wheel_up)
        sub.addAction(self.a_wheel_down)
        m.addSeparator()
        m.addAction(self.a_dark)
        m.addAction(self.a_darkpages)
        m.addAction(self.a_markthumbs)
        m.addSeparator()
        sub = m.addMenu("Highlight")
        for a in self.hl_actions.values():
            sub.addAction(a)
        sub = m.addMenu("Home overview")
        for a in self.home_actions.values():
            sub.addAction(a)
        m.addSeparator()
        m.addAction(self.a_about)

    def _build_toolbar(self):
        self.toolbar = QToolBar("Tools")
        self.toolbar.setMovable(False)
        self.toolbar.setStyleSheet("QToolButton { padding: 2px 2px; } QToolBar { spacing: 0px; }")
        f = QFont(self.toolbar.font())
        if f.pointSizeF() > 8.5:
            f.setPointSizeF(f.pointSizeF() - 1)
        self.toolbar.setFont(f)
        self.toolbar.addAction(self.a_refresh)
        self.toolbar.addAction(self.a_save)
        self.toolbar.addAction(self.a_home)
        self.toolbar.addSeparator()
        full = {"select": "Select text (T)", "textbox": "Text box (X)"}
        for key, a in self.tool_actions.items():
            a.setToolTip(full.get(key, a.text()))
            self.toolbar.addAction(a)
        self.toolbar.addSeparator()
        self._build_nav_widgets(self.toolbar)           # page box, zoom box
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)                      # pushes the Tabs button to the right edge
        self.tabs_button = QToolButton()
        self.tabs_button.setText("Tabs \u2002\u25be")
        self.tabs_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.tabs_button.setToolTip("All open tabs")
        self.tabs_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tabs_menu = QMenu(self.tabs_button)
        self.tabs_menu.aboutToShow.connect(self._fill_tabs_menu)
        self.tabs_button.setMenu(self.tabs_menu)
        self.tabs_button_action = self.toolbar.addWidget(self.tabs_button)
        self.addToolBar(self.toolbar)
        self._build_findbar()

    ZOOM_PRESETS = ("25 %", "50 %", "75 %", "100 %", "125 %", "150 %", "200 %", "300 %", "400 %", "800 %",
                    "Fit width", "Fit page")

    def _build_nav_widgets(self, tb):
        """Page box ("22 / 100" + arrows) and zoom box (+ / -) on the main ribbon `tb`."""
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(46)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.page_edit.setValidator(QIntValidator(1, 999999, self))
        self.page_edit.setToolTip("Page number (type a number and press Enter)")
        self.page_edit.returnPressed.connect(self._goto_page_box)
        self.page_total = QLabel(" / 0  ")
        tb.addWidget(self.page_edit)
        tb.addWidget(self.page_total)
        tb.addAction(self.a_prevpage)
        tb.addAction(self.a_nextpage)
        tb.addSeparator()
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.setFixedWidth(88)
        self.zoom_combo.addItems(self.ZOOM_PRESETS)
        self.zoom_combo.setToolTip("Zoom (choose, or type a percentage and press Enter)")
        self.zoom_combo.activated.connect(lambda idx: self._apply_zoom_text(self.zoom_combo.itemText(idx)))
        self.zoom_combo.lineEdit().returnPressed.connect(
            lambda: self._apply_zoom_text(self.zoom_combo.lineEdit().text()))
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.a_zin)
        tb.addAction(self.a_zout)

    def _goto_page_box(self):
        v = self.view()
        txt = self.page_edit.text().strip()
        if v is not None and v.doc is not None and txt.isdigit():
            v.jump_to(max(1, min(int(txt), v.page_count)) - 1)
            v.setFocus()

    def _apply_zoom_text(self, text):
        v = self.view()
        if v is None or v.doc is None:
            return
        t = text.strip().lower()
        if t.startswith("fit w"):
            v.fit_width()
        elif t.startswith("fit p"):
            v.fit_page()
        else:
            digits = re.sub(r"[^0-9.]", "", t)
            if digits:
                try:
                    v.set_zoom(BASE * max(5.0, min(float(digits), 6400.0)) / 100.0)
                except ValueError:
                    pass
        v.setFocus()

    def _sync_nav(self, v):
        """Refresh the page box and zoom box of the second ribbon from view `v`."""
        has = v is not None and v.doc is not None
        for w_ in (self.page_edit, self.zoom_combo):
            w_.setEnabled(has)
        for a in (self.a_prevpage, self.a_nextpage, self.a_zin, self.a_zout, self.a_refresh):
            a.setEnabled(has)
        if not has:
            self.page_edit.clear()
            self.page_total.setText(" / 0  ")
            self.zoom_combo.setEditText("")
            return
        self.page_total.setText(" / %d  " % v.page_count)
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(v.current_page() + 1))
        if not self.zoom_combo.lineEdit().hasFocus():
            self.zoom_combo.setEditText("%.0f %%" % (v.zoom / BASE * 100))

    # ------------------------------------------------------------------ print
    def print_document(self):
        v = self.view()
        if QPrinter is None or v is None or v.doc is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setFromTo(1, v.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print")
        dlg.setMinMax(1, v.page_count)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        if not run_exec(dlg):
            return
        rng = printer.printRange()
        R = QAbstractPrintDialog.PrintRange
        if rng == R.PageRange:
            first, last = printer.fromPage(), printer.toPage()
            pages = list(range(max(1, first) - 1, min(v.page_count, last or v.page_count)))
        elif rng == R.CurrentPage:
            pages = [v.current_page()]
        else:
            pages = list(range(v.page_count))
        self.print_pages(printer, v, pages)

    def print_pages(self, printer, v, pages):
        """Paint the given pages (0-based) of v, with all annotations, onto `printer`."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        painter = QPainter()
        try:
            if not painter.begin(printer):
                raise RuntimeError("cannot start printing")
            for n, i in enumerate(pages):
                if n:
                    printer.newPage()
                page = v.doc[i]
                z = min(printer.resolution(), 300) / 72.0
                pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888).copy()
                del page
                area = printer.pageRect(QPrinter.Unit.DevicePixel)
                sc = min(area.width() / img.width(), area.height() / img.height())
                tw, th = img.width() * sc, img.height() * sc
                painter.drawImage(QRectF(area.x() + (area.width() - tw) / 2,
                                         area.y() + (area.height() - th) / 2, tw, th), img)
                QApplication.processEvents()
            return True
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Print", "Printing failed:\n%s" % e)
            return False
        finally:
            if painter.isActive():
                painter.end()
            QApplication.restoreOverrideCursor()

    def _build_findbar(self):
        self.findbar = QToolBar("Find")
        self.findbar.setMovable(False)
        self.findbar.addWidget(QLabel(" Find: "))
        self.find_edit = FindEdit()
        self.find_edit.setMinimumWidth(300)
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setPlaceholderText("Text to find (Enter = next, F3 / Shift+F3)")
        self.findbar.addWidget(self.find_edit)
        self.findbar.addAction(self.a_findprev)
        self.findbar.addAction(self.a_findnext)
        self.find_label = QLabel("")
        self.findbar.addWidget(self.find_label)
        self.findbar.addAction(self.a_findclose)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.findbar)
        self.findbar.hide()
        self._find_timer = QTimer(self)
        self._find_timer.setSingleShot(True)
        self._find_timer.setInterval(300)
        self._find_timer.timeout.connect(self._do_search)
        self.find_edit.textChanged.connect(lambda t: self._find_timer.start())
        self.find_edit.returnPressed.connect(self._find_enter)
        self.find_edit.escape.connect(self.close_find)

    def show_find(self):
        v = self.view()
        self.findbar.show()
        if v is not None and v.search_text and not self.find_edit.text():
            self.find_edit.setText(v.search_text)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_find(self):
        self._find_timer.stop()
        self.findbar.hide()
        v = self.view()
        if v is not None:
            v.clear_search()
            v.setFocus()

    def _do_search(self):
        v = self.view()
        if v is not None:
            v.start_search(self.find_edit.text())

    def _find_enter(self):
        v = self.view()
        if v is None:
            return
        if v.search_text == self.find_edit.text().strip() and v.hits:
            v.find_step(1)
        else:
            self._find_timer.stop()
            self._do_search()

    def find_step(self, d):
        v = self.view()
        if v is None:
            return
        if not self.findbar.isVisible():
            self.show_find()
        elif v.hits:
            v.find_step(d)

    def _update_find_label(self, v):
        if v is not self.view():
            return
        if not v.search_text:
            self.find_label.setText("")
        elif v.searching:
            self.find_label.setText("  searching… %d found" % len(v.hits))
        elif v.hits:
            self.find_label.setText("  %d of %d" % (v.hit_idx + 1, len(v.hits)))
        else:
            self.find_label.setText("  no matches")

    SIDEBAR_W = 340

    def _open_docks(self):
        return [d for d in self.docks.values() if not d.isHidden()]

    def _side_extent(self):
        """Width taken by the side-panel area = left edge of the document area.
        Measured on the central widget, so it doesn't matter which panel tab is in front."""
        return self.tabs.x()

    def _apply_width(self, v):
        """Give the side panels the width remembered for v's document (default otherwise)."""
        if v is None or v.doc is None or not v.path or self.isFullScreen():
            return
        self._applying_w = True
        QTimer.singleShot(60, lambda: self._do_apply_width(self.recent.get_width(v.path)))

    def _do_apply_width(self, m):
        docks = self._open_docks()
        if not docks:
            self._applying_w = False
            return
        self._last_target = (m - 6) if m else self.SIDEBAR_W
        self.resizeDocks(docks, [self._last_target] * len(docks), Qt.Orientation.Horizontal)
        if m:
            QTimer.singleShot(150, lambda: self._correct_width(m))
        QTimer.singleShot(600, self._finish_apply_width)

    def _correct_width(self, m):
        """One closed-loop correction so the remembered extent is matched exactly."""
        docks = self._open_docks()
        err = m - self._side_extent()
        if docks and abs(err) > 2:
            self._last_target += err
            self.resizeDocks(docks, [self._last_target] * len(docks), Qt.Orientation.Horizontal)

    def _finish_apply_width(self):
        self._side_base = self._side_extent() if self._open_docks() else None
        self._applying_w = False

    def _side_resized(self):
        """The user dragged the divider: remember the width for this document."""
        v = self.view()
        if (self._applying_w or not self._open_docks() or v is None or v.doc is None
                or not v.path or self.isFullScreen()):
            return
        m = self._side_extent()
        if self._side_base is not None and abs(m - self._side_base) <= 3:
            return
        self._side_base = m
        self.recent.set_width(v.path, m)

    def zoom_speed_dialog(self):
        n, ok = QInputDialog.getInt(
            self, "Zoom speed", "Zoom change per wheel notch (%)\n(used by right-button + wheel and Ctrl + wheel):",
            self.recent.zoom_step, 2, 100)
        if ok:
            self.recent.zoom_step = n
            for v in self._all_views():
                v.zoom_pct = n

    def _panel_closed(self, key):
        self.panel_actions[key].setChecked(False)
        self._remember_panels()

    def _remember_panels(self):
        """Save which panels are open for the document in the current tab."""
        v = self.view()
        if v is not None and v.path and v.doc is not None:
            self.recent.set_panels(v.path, {k: a.isChecked() for k, a in self.panel_actions.items()})

    def _apply_panels(self, v):
        """Load the remembered panel state of v's document into the panel actions."""
        if v is not None and v.path and v.doc is not None:
            for k, on in self.recent.get_panels(v.path).items():
                self.panel_actions[k].setChecked(on)

    def _sync_panels(self, v):
        """Panels are only shown while the current tab has a document (keeps the start page roomy)."""
        if self.isFullScreen():
            return
        for k, d in self.docks.items():
            if v.doc is not None and self.panel_actions[k].isChecked():
                d.show()
            else:
                d.hide()
        for k in ("outline", "thumbs", "marks"):
            if v.doc is not None and self.panel_actions[k].isChecked():
                self.docks[k].raise_()
                break

    def _set_panel(self, key, on):
        d = self.docks[key]
        if on:
            self.panel_actions[key].setChecked(True)
            d.show()
            d.raise_()
            self._remember_panels()
            self._apply_width(self.view())
        else:
            d.close()                      # -> _panel_closed() saves the state

    def _color_rgb(self, kind):
        return COLOR_BY_NAME.get(self.recent.setting("color_" + kind), COLORS[0][1])

    def _set_kind_color(self, kind, name):
        """Remember `name` as the colour of highlight / underline / strikeout / pen (all windows)."""
        if name not in COLOR_BY_NAME:
            return
        self.recent.set_setting("color_" + kind, name)
        for v in self._all_views():
            v.colors[kind] = COLOR_BY_NAME[name]
        self._sync_color_checks()

    def _sync_color_checks(self):
        for kind, acts in self.color_actions.items():
            cur = self.recent.setting("color_" + kind)
            acts[cur if cur in acts else COLORS[0][0]].setChecked(True)

    def _menu_color(self, view, kind, name):
        """Right-click menu: pick a colour. It becomes the tool's colour (shown with a tick in
        Edit) and, if text is selected, is applied to it right away. No tool is switched on."""
        self._set_kind_color(kind, name)
        if view is None or view.doc is None:
            return
        if kind == "highlight" and view.rect_sel is not None:
            view.apply_rect_highlight()
        elif kind in MARKUP and view.sel:
            view.markup_selection(kind)

    FEATURES = (
        "Simple, compact design (SumatraPDF style) - one ribbon, nothing in the way",
        "Dark mode, with optional page inversion",
        "Home overview: your recent (or most opened) books with thumbnails",
        "Pin book: keep a book on the Home page for as long as you want",
        "Mouse zoom: hold the right button and turn the wheel - zooms at the pointer (SumatraPDF inspired)",
        "Tabbed view, or one window per PDF (Tab mode / Window mode)",
        "Single page, facing (two pages) and book view; the layout is remembered per file",
        "Highlight, underline, strikeout, pen, note and text box - each tool has its own colour",
        "Colour menus in Edit and in the right-click menu; text is marked straight from the right-click menu",
        "Undo / Redo for every annotation change",
        "Text boxes with full Unicode text, Bengali included",
        "Find with next / previous, with all hits marked",
        "Outline, thumbnails and bookmarks panels (bookmarks can show page thumbnails)",
        "Clickable links, with Go back (Alt+Left)",
        "Save / Save as, with a question before replacing the original file",
        "Damaged PDFs are repaired in memory so they can still be read",
        "Drag and drop to open, Print, Fullscreen, adjustable zoom speed",
        "Native Linux program - no Wine",
    )

    def about_dialog(self):
        QtCore = sys.modules[Qt.__module__]
        binding = Qt.__module__.split(".")[0]
        try:
            mu = pymupdf.version
            pymupdf_ver, mupdf_ver = mu[0], mu[1]
        except Exception:
            pymupdf_ver = getattr(pymupdf, "__version__", "?")
            mupdf_ver = "?"
        rows = (
            ("Version", APP_VERSION),
            ("License", "AGPL-3.0 (SuReader uses AGPL / GPL components, see below)"),
            ("Rendering engine", "MuPDF %s (by Artifex Software), through PyMuPDF %s" % (mupdf_ver, pymupdf_ver)),
            ("User interface", "Qt %s, %s %s" % (getattr(QtCore, "QT_VERSION_STR", "?"), binding,
                                                getattr(QtCore, "PYQT_VERSION_STR", "?"))),
            ("Python", platform.python_version()),
            ("System", platform.platform()),
            ("Settings file", self.recent.file),
            ("Project page", '<a href="%s">%s</a>' % (APP_URL, APP_URL)),
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("About " + APP_NAME)
        dlg.resize(640, 560)
        lay = QVBoxLayout(dlg)
        head = QLabel("<span style='font-size:20pt'><b>%s</b></span> &nbsp; %s<br>"
                      "Lightweight SumatraPDF-style PDF reader for Linux" % (APP_NAME, APP_VERSION))
        lay.addWidget(head)
        tabs = QTabWidget()
        feat = QTextBrowser()
        feat.setHtml("<ul>%s</ul>" % "".join("<li style='margin-bottom:5px'>%s</li>" % f.replace("&", "&amp;")
                                              for f in self.FEATURES))
        tech = QTextBrowser()
        tech.setOpenExternalLinks(True)
        tech.setHtml(
            "<table cellspacing='0' cellpadding='5'>%s</table><br>"
            "<b>Based on</b><br>"
            "SuReader is built on <b>MuPDF</b> (PDF engine, AGPL-3.0, Artifex Software) via <b>PyMuPDF</b> "
            "(AGPL-3.0), and on <b>Qt</b> through <b>PyQt</b> (GPL-3.0). Because of these licenses SuReader "
            "is released under the AGPL-3.0."
            % "".join("<tr><td><b>%s</b></td><td>%s</td></tr>" % r for r in rows))
        tabs.addTab(feat, "Features")
        tabs.addTab(tech, "Technical info")
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        run_exec(dlg)

    def go_home(self):
        """Show the start page (Frequently Read): an empty tab, or an empty window in window mode."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w.doc is None:
                self.tabs.setCurrentIndex(i)
                if w.home is not None:
                    w.home.refresh()
                return
        if self.recent.setting("open_mode") == "window":
            self._new_window()
        else:
            self.new_tab()

    def set_tool(self, name):
        self.tool = name
        self.tool_actions[name].setChecked(True)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).set_tool(name)

    def set_mode(self, mode):
        v = self.view()
        v.set_view_mode(mode)
        if v.path:
            self.recent.set_mode(v.path, mode)

    # ---------------------------------------------------------------- tabs
    def _remove_markup(self, kind):
        v = self.view()
        if v is None or v.doc is None:
            return
        if not v.remove_markup_from_selection(kind):
            QMessageBox.information(self, "Remove %s" % MARKUP_LABELS[kind],
                                    "Select (with the Select text tool) the part of the %s you want to remove, "
                                    "then use this command again." % MARKUP_LABELS[kind])

    def _undo_redo(self, direction):
        v = self.view()
        if v is not None and v.doc is not None:
            v.undo() if direction < 0 else v.redo()

    def _update_undo(self, v=None):
        v = v or self.view()
        if v is None or v is not self.view():
            return
        cu, cr = (v.doc is not None and v.can_undo()), (v.doc is not None and v.can_redo())
        self.a_undo.setEnabled(cu)
        self.a_redo.setEnabled(cr)
        self.a_undo.setText(("Undo " + v.undo_name()).strip() if cu else "Undo")
        self.a_redo.setText(("Redo " + v.redo_name()).strip() if cr else "Redo")

    def _push_settings(self, v):
        R = self.recent
        v.wheel_down_in = R.setting("wheel_down_in")
        v.hl_mode = R.setting("hl_mode")
        v.colors = {k: self._color_rgb(k) for k in COLOR_KINDS}
        v.set_dark(R.setting("dark"), R.setting("dark") and R.setting("dark_pages"))

    @staticmethod
    def _all_views():
        for win in list(MainWindow.instances):
            for i in range(win.tabs.count()):
                yield win.tabs.widget(i)

    def _sync_settings_checks(self):
        R = self.recent
        (self.a_wheel_down if R.setting("wheel_down_in") else self.a_wheel_up).setChecked(True)
        self.a_dark.setChecked(R.setting("dark"))
        self.a_darkpages.setChecked(R.setting("dark_pages"))
        self.a_markthumbs.setChecked(R.setting("mark_thumbs"))
        self.hl_actions[R.setting("hl_mode")].setChecked(True)
        self.open_actions[R.setting("open_mode")].setChecked(True)
        self.home_actions[R.setting("home_sort")].setChecked(True)
        self._sync_color_checks()

    def _apply_tab_chrome(self):
        """Show / hide the tab bar and the Tabs button (hidden in window mode)."""
        self.tabs.tabBar().setVisible(self._tabs_chrome)
        self.tabs_button_action.setVisible(self._tabs_chrome)

    def _set_open_mode(self, mode):
        self.recent.set_setting("open_mode", mode)
        if mode == "tabs":
            if not self._tabs_chrome:                 # tabs must be visible again right away
                self._tabs_chrome = True
                self._apply_tab_chrome()
        elif self._tabs_chrome:
            QMessageBox.information(
                self, "Window mode",
                "From now on every PDF opens in its own window.\n\n"
                "The Tabs bar and the Tabs button disappear the next time SuReader is started.")

    def _new_window(self):
        w = MainWindow()
        g = self.geometry()
        w.resize(g.size())
        w.move(g.x() + 32, g.y() + 32)
        w.show()
        w.resizeDocks([w.docks["outline"]], [340], Qt.Orientation.Horizontal)
        return w

    def _close_current(self):
        if self._tabs_chrome:
            self.close_tab(self.tabs.currentIndex())
        else:
            self.close()                                # window mode: Ctrl+W closes the window

    def _set_wheel(self, down_in):
        self.recent.set_setting("wheel_down_in", bool(down_in))
        for v in self._all_views():
            v.wheel_down_in = bool(down_in)

    def _set_home_sort(self, mode):
        """Home overview: 'recent' (last opened first) or 'frequent' (most opened first)."""
        self.recent.set_setting("home_sort", mode)
        for v in self._all_views():
            if v.home is not None:
                v.home._paths = None
                if v.home.isVisible():
                    v.home.refresh()

    def _set_hl_mode(self, mode):
        self.recent.set_setting("hl_mode", mode)
        for v in self._all_views():
            v.hl_mode = mode

    def _set_dark(self, on):
        self.recent.set_setting("dark", bool(on))
        self.apply_theme()

    def _set_dark_pages(self, on):
        self.recent.set_setting("dark_pages", bool(on))
        self.apply_theme()

    def _set_mark_thumbs(self, on):
        self.recent.set_setting("mark_thumbs", bool(on))
        for win in list(MainWindow.instances):
            win.sidebar.set_mark_thumbs(bool(on))

    def apply_theme(self):
        R = self.recent
        dark = R.setting("dark")
        app = QApplication.instance()
        if dark:
            app.setStyle("Fusion")
            app.setPalette(make_dark_palette())
        else:
            app.setStyle(self._orig_style)
            app.setPalette(self._orig_palette)
        for v in self._all_views():
            v.set_dark(dark, dark and R.setting("dark_pages"))

    def new_tab(self):
        v = PdfView()
        v.menu_factory = self._context_menu
        self._push_settings(v)
        v.zoom_pct = self.recent.zoom_step
        v.set_tool(self.tool)
        v.changed.connect(lambda v=v: self._view_changed(v))
        v.modified_changed.connect(lambda v=v: self._view_changed(v))
        v.undo_changed.connect(lambda v=v: self._update_undo(v))
        v.loaded.connect(lambda v=v: self._on_loaded(v))
        v.search_changed.connect(lambda v=v: self._update_find_label(v))
        v.content_changed.connect(lambda i, v=v: self._on_content(v, i))
        home = HomePage(self.recent, v.viewport())
        home.open_path.connect(lambda p: self.open_file(p))
        home.open_dialog.connect(lambda: self.open_dialog())
        v.attach_home(home)
        home.set_dark(self.recent.setting("dark"))
        idx = self.tabs.addTab(v, "New tab")
        self.tabs.setCurrentIndex(idx)
        return v

    def _step_tab(self, d):
        n = self.tabs.count()
        self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def _ask_unsaved(self, v):
        """Ask what to do with unsaved annotations -> 'replace' | 'saveas' | 'discard' | 'cancel'."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Unsaved annotations")
        box.setText("\u201c%s\u201d has annotations that are not saved yet." % os.path.basename(v.path or "document"))
        box.setInformativeText("Replace the original file, or keep the original and save the "
                               "annotated version under a new name?")
        b_rep = box.addButton("Replace original", QMessageBox.ButtonRole.AcceptRole)
        b_new = box.addButton("Save as new file\u2026", QMessageBox.ButtonRole.AcceptRole)
        b_dis = box.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole)
        b_can = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_new)
        box.setEscapeButton(b_can)
        run_exec(box)
        c = box.clickedButton()
        if c is b_rep:
            return "replace"
        if c is b_new:
            return "saveas"
        if c is b_dis:
            return "discard"
        return "cancel"

    def _confirm(self, v):
        """True if it is OK to close v (annotations saved or deliberately discarded)."""
        if not v.modified:
            return True
        choice = self._ask_unsaved(v)
        if choice == "replace":
            return self._replace_view(v, reload=False)
        if choice == "saveas":
            return self._save_as_view(v, reload=False)
        return choice == "discard"

    def close_tab(self, idx):
        v = self.tabs.widget(idx)
        if v is None or not self._confirm(v):
            return
        self.tabs.removeTab(idx)
        v.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()

    def _tab_changed(self, idx):
        v = self.tabs.widget(idx)
        if v is None:
            self.sidebar.set_view(None)
            return
        self.mode_actions[v.mode].setChecked(True)
        self._side_key = None
        self.sidebar.set_view(v)
        self._apply_panels(v)
        self._sync_panels(v)
        self._apply_width(v)
        self.find_edit.blockSignals(True)
        self.find_edit.setText(v.search_text)
        self.find_edit.blockSignals(False)
        self._update_find_label(v)
        self._update_undo(v)
        self._sync_nav(v)
        self._view_changed(v)

    def _on_loaded(self, v):
        if v is self.view():
            self._side_key = None
            self.sidebar.set_view(v, fresh=True)
            self._apply_panels(v)
            self._sync_panels(v)
            self._apply_width(v)
            want = "outline" if self.sidebar.has_toc else "thumbs"
            if self.panel_actions[want].isChecked():
                self.docks[want].raise_()

    def _on_content(self, v, i):
        if v is self.view():
            self.sidebar.refresh_thumb(i)

    def _add_bookmark(self):
        self._set_panel("marks", True)
        self.panel_actions["marks"].setChecked(True)
        self.sidebar.add_bookmark()

    def _view_changed(self, v):
        idx = self.tabs.indexOf(v)
        if idx < 0:
            return
        name = os.path.basename(v.path) if v.path else "New tab"
        self.tabs.setTabText(idx, ("* " if v.modified else "") + name)
        self.tabs.setTabToolTip(idx, v.path or "")
        if v is self.view():
            self._sync_nav(v)
            if v.doc is not None:
                key = (id(v), v.current_page())
                if key != self._side_key:
                    self._side_key = key
                    self.sidebar.select_page(key[1])
                self.setWindowTitle("%s%s%s — page %d/%d — %.0f%%" % (
                    "* " if v.modified else "", name, " (repaired)" if v.repaired else "",
                    v.current_page() + 1, v.page_count, v.zoom / BASE * 100))
            else:
                self.setWindowTitle("SuReader")

    # --------------------------------------------------------------- files
    def open_dialog(self):
        v = self.view()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", os.path.dirname(v.path) if v and v.path else "",
            "Documents (*.pdf *.epub *.xps *.cbz *.mobi *.fb2);;All files (*)")
        for p in paths:
            self.open_file(p)

    def _fill_tabs_menu(self):
        m = self.tabs_menu
        m.clear()
        cur = self.tabs.currentIndex()
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            a = m.addAction("%d  %s" % (i + 1, self.tabs.tabText(i).replace("&", "&&")))
            a.setCheckable(True)
            a.setChecked(i == cur)
            if w is not None and w.path:
                a.setToolTip(w.path)
                a.setStatusTip(w.path)
            a.triggered.connect(lambda checked=False, i=i: self.tabs.setCurrentIndex(i))

    def _fill_recent(self):
        m = self.recent_menu
        m.clear()
        paths = self.recent.recent(10)
        if not paths:
            m.addAction("(no recent files)").setEnabled(False)
            return
        for i, pth in enumerate(paths):
            name = os.path.basename(pth).replace("&", "&&")
            a = m.addAction(("&%d  %s" % (i + 1, name)) if i < 9 else ("%d  %s" % (i + 1, name)))
            a.setToolTip(pth)
            a.setStatusTip(pth)
            a.triggered.connect(lambda checked=False, p=pth: self.open_file(p))
        m.addSeparator()
        m.addAction("Clear recent list", lambda checked=False: self._clear_recent())

    def _clear_recent(self):
        self.recent.clear()
        for i in range(self.tabs.count()):          # refresh start pages
            h = self.tabs.widget(i).home
            if h is not None:
                h._paths = None

    def open_file(self, path):
        real = os.path.realpath(path)
        for win in list(MainWindow.instances):          # already open (in any window)? show it
            for i in range(win.tabs.count()):
                w = win.tabs.widget(i)
                if w.path and os.path.realpath(w.path) == real:
                    win.tabs.setCurrentIndex(i)
                    win.raise_()
                    win.activateWindow()
                    self.recent.touch(path, bump=False)     # just make it the most recent
                    return
        cur = self.view()
        if self.recent.setting("open_mode") == "window" and cur is not None and cur.doc is not None:
            self._new_window().open_file(path)              # window mode: this window is taken
            return
        fresh = cur is not None and cur.doc is None
        v = cur if fresh else self.new_tab()
        try:
            v.mode = self.recent.get_mode(path)     # remembered page layout for this file
            v.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Error", "Cannot open file:\n%s" % e)
            if not fresh:
                self.close_tab(self.tabs.indexOf(v))
            return
        self.recent.touch(path)
        if v.repaired:
            QMessageBox.information(
                self, "File repaired",
                "The internal index of this PDF was damaged, so it could not be read normally "
                "(this can happen after an interrupted or repeated in-place save).\n\n"
                "SuReader repaired it in memory. Your pages and annotations are intact.\n"
                "Press Save and choose Yes to write the repaired file permanently.")
        if v is self.view():
            self.mode_actions[v.mode].setChecked(True)
        self._view_changed(v)

    def _replace_view(self, v, reload=False):
        if v.doc is None:
            return False
        if not v.doc.is_pdf:
            QMessageBox.information(self, "Save", "Only PDF files can be saved.")
            return False
        try:
            v.save(reload=reload)
            return True
        except Exception as e:
            QMessageBox.warning(
                self, "Cannot save",
                "Could not replace the original file:\n%s\n\nThe original file was not changed. "
                "Use \u201cSave as\u2026\u201d to write a copy somewhere else." % e)
            return False

    def _ask_save_here(self, v):
        """'Save these changes to this same file?'  -> 'yes' | 'no' | 'cancel' (Esc / X)."""
        box = AskBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Save changes")
        box.setText("Save these changes to this same file?")
        box.setInformativeText("%s\n%s\n\nChoose \u201cNo\u201d to save them to a different file instead."
                               % (os.path.basename(v.path or ""), os.path.dirname(v.path or "")))
        yes = box.addButton("Yes", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("No", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(yes)
        run_exec(box)
        c = box.clickedButton()
        return "yes" if c is yes else ("no" if c is no else "cancel")

    def _save_view(self, v):
        """Save button / Ctrl+S: Yes = replace this file, No = pick another file name."""
        if v.doc is None:
            return False
        if not v.doc.is_pdf:
            QMessageBox.information(self, "Save", "Only PDF files can be saved.")
            return False
        if not v.modified and not v.repaired:
            QMessageBox.information(self, "Save", "There are no unsaved changes.")
            return False
        choice = self._ask_save_here(v)
        if choice == "yes":
            return self._replace_view(v)
        if choice == "no":
            return self._save_as_view(v)
        return False

    def _save_as_view(self, v, reload=False):
        if v.doc is None or not v.doc.is_pdf:
            return False
        base, ext = os.path.splitext(v.path or "document.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save as", base + "_annotated" + (ext or ".pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            v.save_as(path, reload=reload)
            self.recent.touch(path, bump=False)
            return True
        except Exception as e:
            QMessageBox.warning(self, "Cannot save", "Could not save the file:\n%s" % e)
            return False

    def save(self):
        self._save_view(self.view())

    def save_as(self):
        self._save_as_view(self.view())

    def reload(self):
        v = self.view()
        if v.path and self._confirm(v):
            v.modified = False
            v.load(v.path, keep=True)

    def goto_dialog(self):
        v = self.view()
        if v.doc is None:
            return
        n, ok = QInputDialog.getInt(self, "Go to page", "Page (1–%d):" % v.page_count,
                                    v.current_page() + 1, 1, v.page_count)
        if ok:
            v.goto_page(n - 1)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.toolbar.show()
            self.tabs.tabBar().setVisible(self._tabs_chrome)
            for k, d in self.docks.items():
                if self._open_panels.get(k):
                    d.show()
            if self._open_panels.get("outline"):
                self.docks["outline"].raise_()
            self.findbar.setVisible(self._find_was_visible)
        else:
            self._open_panels = {k: a.isChecked() for k, a in self.panel_actions.items()}
            self._find_was_visible = self.findbar.isVisible()
            self.showFullScreen()
            for d in self.docks.values():
                d.hide()
            self.findbar.hide()
            self.menuBar().hide()
            self.toolbar.hide()
            self.tabs.tabBar().hide()

    def _context_menu(self, view, pos):
        m = QMenu(self)
        for act in (self.a_bookmark, self.a_goto, self.a_back, self.a_find):
            m.addAction(act)
        # things that depend on what is under the mouse / selected
        groups = []
        if view.doc is not None:
            text = view.sel_text() if view.sel else ""
            if text:
                g = [("Copy text", lambda checked=False: view.copy_selection())]
                for kind in MARKUP:
                    if view.markup_overlaps(kind):
                        g.append(("Remove %s from selection" % MARKUP_LABELS[kind],
                                  lambda checked=False, k=kind: view.remove_markup_from_selection(k)))
                groups.append(g)
            if view.rect_sel is not None:
                groups.append([("Apply highlight to the rectangle", lambda checked=False: view.apply_rect_highlight()),
                               ("Cancel the rectangle", lambda checked=False: view.cancel_rect())])
            page, annot = view.annot_under(pos)
            if annot is not None:
                # keep only plain numbers in the menu callbacks: a menu that holds on to Page /
                # Annot objects would stop undo/redo from reloading that page
                pno, xref, atype = page.number, annot.xref, annot.type[1]
                del page, annot
                g = []
                if atype == "Text":
                    g.append(("Edit note", lambda checked=False, i=pno, x=xref: view.edit_note_xref(i, x)))
                if atype == "FreeText":
                    g.append(("Edit text box", lambda checked=False, i=pno, x=xref: view.edit_textbox_xref(i, x)))
                g.append(("Delete annotation", lambda checked=False, i=pno, x=xref: view.delete_annot_xref(i, x)))
                groups.append(g)
        for g in groups:
            m.addSeparator()
            for label, fn in g:
                m.addAction(label, fn)
        m.addSeparator()
        for kind in COLOR_KINDS:
            sub = m.addMenu(KIND_LABELS[kind])
            for name, rgb in COLORS:
                sub.addAction(name, lambda checked=False, k=kind, n=name: self._menu_color(view, k, n))
        m.addAction("Note", lambda checked=False: view.note_at(pos))
        m.addAction("Textbox", lambda checked=False: view.textbox_at(pos))
        m.addSeparator()
        m.addAction(self.a_fs)
        return m

    def closeEvent(self, ev):
        for i in range(self.tabs.count()):
            if not self._confirm(self.tabs.widget(i)):
                ev.ignore()
                return
        for i in range(self.tabs.count()):
            self.tabs.widget(i).modified = False
        if self in MainWindow.instances:
            MainWindow.instances.remove(self)
        ev.accept()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            self.open_file(u.toLocalFile())


_last_err = [0.0]


def _excepthook(t, e, tb):
    traceback.print_exception(t, e, tb)
    now = time.monotonic()
    if now - _last_err[0] > 3:             # don't spam dialogs
        _last_err[0] = now
        try:
            QMessageBox.critical(None, "Unexpected error", "%s: %s" % (t.__name__, e))
        except Exception:
            pass


def main():
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    w.resizeDocks([w.docks["outline"]], [340], Qt.Orientation.Horizontal)
    for p in sys.argv[1:]:
        w.open_file(p)
    sys.exit(run_exec(app))


if __name__ == "__main__":
    main()
