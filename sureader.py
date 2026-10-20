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
                  P pen  N note  E delete annotation      (Ctrl+C copies selection)
* Start page      empty tab shows your most-read documents (click to open, right-click to remove)
* Panels          Outline (F6), Thumbnails (F7), Bookmarks (F8): each has its own close (X)
                  button and can be re-opened from the View menu
                  Ctrl+D add bookmark (right-click a bookmark to rename/delete)
* Search          Ctrl+F find, Enter / F3 next, Shift+F3 previous, Esc close
* Links           click internal / http(s) links;  Alt+Left goes back
* Save            Ctrl+S (in place)  Ctrl+Shift+S (save as)
* View            Ctrl+1 actual size  Ctrl+2 fit page  Ctrl+3 fit width  Ctrl+= / Ctrl+-
                  Ctrl+G go to page   Ctrl+R reload    F11 fullscreen
"""
import sys
import os
import json
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
    from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QSize, QPoint, QObject, QUrl, pyqtSignal
    from PyQt6.QtGui import (QImage, QPainter, QColor, QAction, QActionGroup,
                             QKeySequence, QPen, QPixmap, QIcon, QDesktopServices)
    from PyQt6.QtWidgets import (
        QAbstractScrollArea, QApplication, QComboBox, QFileDialog, QInputDialog,
        QLineEdit, QMainWindow, QMenu, QMessageBox, QTabWidget, QToolBar,
        QDockWidget, QListView, QListWidget, QListWidgetItem, QTreeWidget,
        QTreeWidgetItem, QLabel, QFrame, QGridLayout, QVBoxLayout, QScrollArea, QWidget)
except ImportError:                      # Qt5 (older distros, e.g. glibc < 2.33)
    from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QSize, QPoint, QObject, QUrl, pyqtSignal
    from PyQt5.QtGui import (QImage, QPainter, QColor, QKeySequence, QPen,
                             QPixmap, QIcon, QDesktopServices)
    from PyQt5.QtWidgets import (
        QAbstractScrollArea, QApplication, QComboBox, QFileDialog, QInputDialog,
        QLineEdit, QMainWindow, QMenu, QMessageBox, QTabWidget, QToolBar,
        QAction, QActionGroup, QDockWidget, QListView, QListWidget,
        QListWidgetItem, QTreeWidget, QTreeWidgetItem, QLabel, QFrame, QGridLayout,
        QVBoxLayout, QScrollArea, QWidget)


def ev_pos(ev):
    """Event position in widget coordinates (QPoint), Qt5 and Qt6."""
    return ev.position().toPoint() if hasattr(ev, "position") else ev.pos()


def ev_global(ev):
    return ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()


def run_exec(obj, *a):
    return (obj.exec if hasattr(obj, "exec") else obj.exec_)(*a)


BASE = 96.0 / 72.0          # 100% zoom == 96 dpi, like SumatraPDF
MIN_Z, MAX_Z = 0.05 * BASE, 64 * BASE
MARGIN, GAP = 10, 10
FULL_RENDER_LIMIT = 16_000_000   # pixels; bigger pages are rendered clipped

COLORS = [("Yellow", (1.0, 0.92, 0.2)), ("Red", (0.9, 0.15, 0.15)),
          ("Green", (0.35, 0.85, 0.35)), ("Pink", (1.0, 0.5, 0.75)),
          ("Blue", (0.3, 0.55, 1.0)), ("Orange", (1.0, 0.6, 0.15)),
          ("Black", (0.0, 0.0, 0.0))]
TOOLS = [("hand", "Hand", "H"), ("select", "Select text", "T"),
         ("highlight", "Highlight", "L"), ("underline", "Underline", "U"),
         ("strike", "Strikeout", "K"), ("pen", "Pen", "P"),
         ("note", "Note", "N"), ("erase", "Delete annot.", "E")]
MARKUP = ("highlight", "underline", "strike")
CURSORS = {"hand": Qt.CursorShape.OpenHandCursor, "select": Qt.CursorShape.IBeamCursor,
           "highlight": Qt.CursorShape.IBeamCursor, "underline": Qt.CursorShape.IBeamCursor,
           "strike": Qt.CursorShape.IBeamCursor, "pen": Qt.CursorShape.CrossCursor,
           "note": Qt.CursorShape.CrossCursor, "erase": Qt.CursorShape.PointingHandCursor}


def qcolor(rgb, alpha=255):
    return QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), alpha)


class PdfView(QAbstractScrollArea):
    changed = pyqtSignal()
    modified_changed = pyqtSignal()
    loaded = pyqtSignal()
    content_changed = pyqtSignal(int)
    search_changed = pyqtSignal()

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
        self.tool = "hand"
        self.color = COLORS[0][1]
        self.menu_factory = None
        self.links_cache = {}
        self.nav_stack = []
        self._over_link = False
        self.home = None
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
    def load(self, path, keep=False):
        doc = pymupdf.open(path)
        if doc.needs_pass:
            pw, ok = QInputDialog.getText(self, "Password", "Document is encrypted:",
                                          QLineEdit.EchoMode.Password)
            if not ok or not doc.authenticate(pw):
                raise ValueError("Wrong password")
        prev = self.current_page() if (keep and self.doc is not None and not self.doc.is_closed) else 0
        old, self.doc = self.doc, doc
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.path = path
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

    def save(self):
        """In-place (incremental) save. Returns False if that is not possible."""
        if self.doc is None or not self.path:
            return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if not self.doc.can_save_incrementally():
                return False
            self.doc.saveIncr()
        except Exception:
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._set_modified(False)
        return True

    def save_as(self, path):
        """Full save to `path` (may be the current file: written to a temp file first)."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        target = None
        try:
            same = os.path.abspath(path) == os.path.abspath(self.path or "")
            target = path + ".tmp~" if same else path
            kw = {"garbage": 1, "deflate": False}
            if self.doc.is_encrypted:
                kw["encryption"] = pymupdf.PDF_ENCRYPT_KEEP
            self.doc.save(target, **kw)
            if same:
                os.replace(target, path)      # old handle stays valid on Linux
        except Exception as e:
            QApplication.restoreOverrideCursor()
            if target and target != path and os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
            QMessageBox.warning(self, "Error", "Cannot save:\n%s" % e)
            return False
        QApplication.restoreOverrideCursor()
        self.modified = False
        self.load(path, keep=True)
        self.modified_changed.emit()
        return True

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
        self.viewport().update()
        self.changed.emit()

    # --------------------------------------------------------------- tools
    def set_tool(self, tool):
        self.tool = tool
        self._pan = None
        self._over_link = False
        self.viewport().setCursor(CURSORS.get(tool, Qt.CursorShape.ArrowCursor))

    def _need_pdf(self):
        if self.doc is not None and self.doc.is_pdf:
            return True
        QMessageBox.information(self, "Annotations", "Annotations are supported for PDF files only.")
        return False

    def invalidate(self, i):
        for k in [k for k in self.cache if k[0] == i]:
            del self.cache[k]
        self.last.pop(i, None)
        self.viewport().update()
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
        done = False
        for i in range(n[0][0], n[1][0] + 1):
            rects = self.sel_rects(i)
            if not rects:
                continue
            page = self.doc[i]
            fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                  "strike": page.add_strikeout_annot}[kind]
            a = fn(quads=rects)
            if a is None:
                continue
            a.set_colors(stroke=self.color)
            a.update()
            self.invalidate(i)
            done = True
        if done:
            self._set_modified()
        self.sel = None
        self.viewport().update()
        return done

    def _finish_stroke(self):
        pts, i = self._stroke, self._stroke_page
        self._stroke = self._stroke_page = None
        if len(pts) >= 2 and self._need_pdf():
            a = self.doc[i].add_ink_annot([[(float(x), float(y)) for x, y in pts]])
            a.set_border(width=1.8)
            a.set_colors(stroke=self.color)
            a.update()
            self.invalidate(i)
            self._set_modified()
        self.viewport().update()

    def add_note(self, i, x, y, text):
        a = self.doc[i].add_text_annot(pymupdf.Point(x, y), text, icon="Note")
        a.set_colors(stroke=self.color)
        a.update()
        self.invalidate(i)
        self._set_modified()

    def annot_under(self, pos):
        """Smallest annotation under viewport point `pos` -> (page, annot) or (None, None)."""
        if self.doc is None or not self.doc.is_pdf:
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
        page.delete_annot(annot)
        self.invalidate(idx)
        self._set_modified()

    def edit_note(self, annot):
        text, ok = QInputDialog.getMultiLineText(self, "Note", "Edit note:",
                                                 annot.info.get("content", ""))
        if ok:
            annot.set_info(content=text)
            annot.update()
            self._set_modified()

    def _click(self, pos):
        if self.tool in ("hand", "select"):
            l = self.link_at(pos)
            if l is not None:
                self.follow_link(l)
                return
        page, a = self.annot_under(pos)
        if a is not None and a.type[1] == "Text":
            self.edit_note(a)

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

    def _hover(self, pos):
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
        p.fillRect(QRectF(x, y, w, h), QColor("white"))
        if w * dpr * h * dpr <= FULL_RENDER_LIMIT:
            key = (i, round(z, 4), dpr)
            img = self.cache.get(key)
            if img is None:
                if self._fast and i in self.last:
                    p.drawImage(QRectF(x, y, w, h), self.last[i][1])
                    return
                pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(z * dpr, z * dpr), alpha=False)
                img = self._qimage(pix)
                self.cache[key] = img
                while len(self.cache) > 12:
                    self.cache.popitem(last=False)
                self.last[i] = (z, img)
            else:
                self.cache.move_to_end(key)
            p.drawImage(QRectF(x, y, w, h), img)
        else:
            if self._fast:
                return
            vw, vh = self.viewport().width(), self.viewport().height()
            l, t = max(0.0, -x) / z, max(0.0, -y) / z
            r, b = min(w, vw - x) / z, min(h, vh - y) / z
            if r <= l or b <= t:
                return
            pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(z * dpr, z * dpr),
                                         clip=pymupdf.Rect(l, t, r, b), alpha=False)
            p.drawImage(QRectF(x + l * z, y + t * z, pix.width / dpr, pix.height / dpr),
                        self._qimage(pix))

    def _paint_overlays(self, p, i, x, y):
        z = self.zoom
        for r in self.sel_rects(i):
            p.fillRect(QRectF(x + r.x0 * z, y + r.y0 * z, r.width * z, r.height * z),
                       QColor(40, 110, 255, 90))
        for k, r in self.hit_map.get(i, ()):
            cur = k == self.hit_idx
            p.fillRect(QRectF(x + r.x0 * z, y + r.y0 * z, r.width * z, r.height * z),
                       QColor(255, 140, 0, 150) if cur else QColor(255, 235, 0, 110))
        if self._stroke is not None and self._stroke_page == i:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(qcolor(self.color), max(1.0, 1.8 * z)))
            pts = self._stroke
            for a, b in zip(pts, pts[1:]):
                p.drawLine(QPointF(x + a[0] * z, y + a[1] * z), QPointF(x + b[0] * z, y + b[1] * z))

    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(0x80, 0x80, 0x80))
        if self.doc is None:
            p.setPen(QColor("white"))
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       "Ctrl+O to open a PDF, or drop a file here")
            return
        hs, vs = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        vh, xo, z = self.viewport().height(), self._x_off(), self.zoom
        for r, row in enumerate(self.rows):
            top = self.row_tops[r] - vs
            if top + self.row_hs[r] < 0:
                continue
            if top > vh:
                break
            for i in row:
                if i < 0:
                    continue
                px, py = self.page_pos[i]
                x, y = xo + px - hs, py - vs
                self._paint_page(p, i, x, y, self.sizes[i][0] * z, self.sizes[i][1] * z)
                self._paint_overlays(p, i, x, y)

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
                self.zoom_by(1.1 ** (delta / 120.0), (pos.x(), pos.y()))
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
        if ev.button() != Qt.MouseButton.LeftButton or self.doc is None:
            return
        pos = ev_pos(ev)
        self._press, self._moved = pos, False
        t = self.tool
        if t == "hand":
            self._pan = pos
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
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
        if self._pan is not None:
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
            if self._pan is not None:
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
            elif self._stroke is not None:
                self._finish_stroke()
            elif self._press is not None and self.tool == "select":
                self._click(pos)
            self._press = None
            self.viewport().update()
        elif ev.button() == Qt.MouseButton.RightButton:
            if not self._right_zoomed and self.menu_factory:
                run_exec(self.menu_factory(self, pos), ev_global(ev))
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
        elif k == K.Key_Escape:
            self.sel = None
            self.viewport().update()
        else:
            super().keyPressEvent(ev)


class BookmarkStore:
    """Per-file user bookmarks, kept in ~/.config/sumatra-linux/bookmarks.json"""

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


class ThumbList(QListWidget):
    shown = pyqtSignal()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.shown.emit()


class Dock(QDockWidget):
    closed = pyqtSignal()

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
        self._loaded = set()
        UR = Qt.ItemDataRole.UserRole
        self.UR = UR

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda it, col=0: self._goto(it.data(0, UR)))

        self.thumbs = ThumbList()
        self.thumbs.setViewMode(QListView.ViewMode.IconMode)
        self.thumbs.setFlow(QListView.Flow.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListView.Movement.Static)
        self.thumbs.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbs.setIconSize(QSize(self.TW, self.TH))
        self.thumbs.setGridSize(QSize(self.TW + 70, self.TH + 36))
        self.thumbs.itemClicked.connect(lambda it: self._goto(it.data(UR)))
        self.thumbs.verticalScrollBar().valueChanged.connect(self._sched_thumbs)
        self.thumbs.shown.connect(self._sched_thumbs)

        self.marks = MarkList()
        self.marks.itemClicked.connect(lambda it: self._goto(it.data(UR)))
        self.marks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.marks.customContextMenuRequested.connect(self._marks_menu)
        self.marks.delete_requested.connect(self._delete_selected)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._load_thumbs)

    def _goto(self, page):
        if self.view is not None and page is not None:
            self.view.jump_to(int(page))
            self.view.setFocus()

    # ------------------------------------------------------------- content
    def set_view(self, v, fresh=False):
        self.view = v
        self.tree.clear()
        self.thumbs.clear()
        self._loaded = set()
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
        ph = QPixmap(self.TW, self.TH)
        ph.fill(QColor("white"))
        pp = QPainter(ph)
        pp.setPen(QColor(150, 150, 150))
        pp.drawRect(0, 0, self.TW - 1, self.TH - 1)
        pp.end()
        icon = QIcon(ph)
        for i in range(v.page_count):
            it = QListWidgetItem(icon, str(i + 1))
            it.setData(self.UR, i)
            self.thumbs.addItem(it)
        self._refresh_marks()
        self.select_page(v.current_page())
        self._sched_thumbs()

    def select_page(self, page):
        if self.thumbs.count() > page >= 0:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(page)
            self.thumbs.blockSignals(False)
            if self.thumbs.isVisible():
                self.thumbs.scrollToItem(self.thumbs.item(page))

    # ----------------------------------------------------------- thumbnails
    def _sched_thumbs(self, *a):
        self._timer.start()

    def _render_thumb(self, r):
        v = self.view
        page = v.doc[r]
        z = self.TW / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        pp = QPainter(pm)
        pp.setPen(QColor(150, 150, 150))
        pp.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        pp.end()
        self.thumbs.item(r).setIcon(QIcon(pm))
        self._loaded.add(r)

    def _load_thumbs(self):
        v = self.view
        if v is None or v.doc is None or not self.thumbs.isVisible():
            return
        n = self.thumbs.count()
        if n == 0:
            return
        first = self.thumbs.indexAt(QPoint(10, 10)).row()
        last = self.thumbs.indexAt(QPoint(10, self.thumbs.viewport().height() - 10)).row()
        first = 0 if first < 0 else first
        last = n - 1 if last < 0 else last
        try:
            for r in range(max(0, first - 2), min(n, last + 3)):
                if r not in self._loaded:
                    self._render_thumb(r)
        except Exception:
            pass

    def refresh_thumb(self, i):
        if self.view is not None and i in self._loaded and i < self.thumbs.count():
            try:
                self._render_thumb(i)
            except Exception:
                pass

    # ------------------------------------------------------------ bookmarks
    def _items(self):
        v = self.view
        return self.store.get(v.path) if v is not None and v.path else []

    def _refresh_marks(self):
        self.marks.clear()
        for b in self._items():
            it = QListWidgetItem("%s  (p. %d)" % (b["label"], b["page"] + 1))
            it.setData(self.UR, b["page"])
            self.marks.addItem(it)

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

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.file)
        except Exception:
            pass

    def touch(self, path):
        d = self.data["docs"].setdefault(os.path.realpath(path), {"n": 0, "t": 0})
        d["n"] += 1
        d["t"] = time.time()
        self._save()

    def remove(self, path):
        self.data["docs"].pop(path, None)
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

    def top(self, n=10):
        items = [(k, v) for k, v in self.data["docs"].items() if os.path.isfile(k)]
        items.sort(key=lambda kv: (-kv[1].get("n", 0), -kv[1].get("t", 0)))
        return [k for k, _ in items[:n]]

    def thumb_path(self, path):
        st = os.stat(path)
        h = hashlib.sha1(("%s|%d|%d" % (path, st.st_mtime_ns, st.st_size)).encode()).hexdigest()
        return os.path.join(self.thumb_dir, h + ".png")


class Card(QWidget):
    """One document on the start page: thumbnail + file name."""
    W, H = 212, 150
    clicked = pyqtSignal()
    remove_requested = pyqtSignal()

    def __init__(self, path):
        super().__init__()
        self.path = path
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
        self.name.setText(self.name.fontMetrics().elidedText(
            os.path.basename(path), Qt.TextElideMode.ElideRight, self.W - 6))
        self.name.setToolTip(path)
        lay.addWidget(self.thumb)
        lay.addWidget(self.name)
        self.setFixedWidth(self.W + 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_thumb(self, pm):
        if pm is None or pm.isNull():
            self.thumb.setText(os.path.splitext(self.path)[1].upper().lstrip(".") or "FILE")
        else:
            self.thumb.setPixmap(pm)

    def _menu(self, pos):
        m = QMenu(self)
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
        self.title = QLabel("Frequently Read")
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

    def _toggle(self):
        self.store.hide = not self.store.hide
        self._paths = None
        self.refresh()

    def refresh(self):
        hide = self.store.hide
        paths = [] if hide else self.store.top(self.MAX)
        key = (hide, tuple(paths))
        if key == self._paths:
            return
        self._paths = key
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        for pth in paths:
            c = Card(pth)
            c.clicked.connect(lambda pth=pth: self.open_path.emit(pth))
            c.remove_requested.connect(lambda pth=pth: self._remove(pth))
            self.cards.append(c)
        self.title.setVisible(bool(paths))
        self.grid_host.setVisible(bool(paths))
        have_any = bool(self.store.data["docs"])
        self.toggle_link.setVisible(have_any)
        self.toggle_link.setText('<a href="t" style="color:#0000cc">%s</a>' % (
            "Show frequently read" if hide else "Hide frequently read"))
        self._cols = 0
        self._relayout()
        self._queue = list(self.cards)
        self._timer.start()

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


class FindEdit(QLineEdit):
    escape = pyqtSignal()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(ev)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tool = "hand"
        self.color = COLORS[0][1]
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self.store = BookmarkStore()
        self.recent = RecentStore()
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
        self._open_panels = {}
        self._find_was_visible = False
        self.setAcceptDrops(True)
        self.resize(1100, 850)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.new_tab()

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
        self.a_closetab = self._act("Close tab", ["Ctrl+W"], lambda: self.close_tab(self.tabs.currentIndex()))
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
            self.docks[key].closed.connect(lambda k=key: self.panel_actions[k].setChecked(False))
        self.a_find = self._act("Find…", ["Ctrl+F"], lambda: self.show_find())
        self.a_findnext = self._act("Find next", ["F3"], lambda: self.find_step(1))
        self.a_findprev = self._act("Find previous", ["Shift+F3"], lambda: self.find_step(-1))
        self.a_findclose = self._act("✕ Close", None, lambda: self.close_find())
        self.a_back = self._act("Go back", ["Alt+Left"], lambda: self.view().nav_back())
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
        for a in (self.a_open, self.a_save, self.a_saveas, self.a_reload, self.a_closetab):
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
        for a in (self.a_find, self.a_findnext, self.a_findprev, self.a_copy):
            m.addAction(a)
        m = mb.addMenu("&Annotate")
        for a in self.tool_actions.values():
            m.addAction(a)

    def _build_toolbar(self):
        self.toolbar = QToolBar("Tools")
        self.toolbar.setMovable(False)
        for a in self.tool_actions.values():
            self.toolbar.addAction(a)
        self.toolbar.addSeparator()
        self.combo = QComboBox()
        for name, rgb in COLORS:
            pm = QPixmap(16, 16)
            pm.fill(qcolor(rgb))
            self.combo.addItem(QIcon(pm), name, rgb)
        self.combo.currentIndexChanged.connect(self._color_changed)
        self.toolbar.addWidget(self.combo)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.a_save)
        self.addToolBar(self.toolbar)
        self._build_findbar()

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

    def _sync_panels(self, v):
        """Panels are only shown while the current tab has a document (keeps the start page roomy)."""
        if self.isFullScreen():
            return
        for k, d in self.docks.items():
            if v.doc is not None and self.panel_actions[k].isChecked():
                d.show()
            else:
                d.hide()
        if v.doc is not None and self.panel_actions["outline"].isChecked():
            self.docks["outline"].raise_()

    def _set_panel(self, key, on):
        d = self.docks[key]
        if on:
            d.show()
            d.raise_()
        else:
            d.close()

    def _color_changed(self, idx):
        self.color = self.combo.itemData(idx)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).color = self.color

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
    def new_tab(self):
        v = PdfView()
        v.menu_factory = self._context_menu
        v.color = self.color
        v.set_tool(self.tool)
        v.changed.connect(lambda v=v: self._view_changed(v))
        v.modified_changed.connect(lambda v=v: self._view_changed(v))
        v.loaded.connect(lambda v=v: self._on_loaded(v))
        v.search_changed.connect(lambda v=v: self._update_find_label(v))
        v.content_changed.connect(lambda i, v=v: self._on_content(v, i))
        home = HomePage(self.recent, v.viewport())
        home.open_path.connect(lambda p: self.open_file(p))
        home.open_dialog.connect(lambda: self.open_dialog())
        v.attach_home(home)
        idx = self.tabs.addTab(v, "New tab")
        self.tabs.setCurrentIndex(idx)
        return v

    def _step_tab(self, d):
        n = self.tabs.count()
        self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def _confirm(self, v):
        if not v.modified:
            return True
        B = QMessageBox.StandardButton
        r = QMessageBox.question(self, "Unsaved changes",
                                 "Save changes to %s?" % os.path.basename(v.path or "document"),
                                 B.Save | B.Discard | B.Cancel)
        if r == B.Cancel:
            return False
        if r == B.Save:
            return self._save_view(v)
        return True

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
        self._sync_panels(v)
        self.find_edit.blockSignals(True)
        self.find_edit.setText(v.search_text)
        self.find_edit.blockSignals(False)
        self._update_find_label(v)
        self._view_changed(v)

    def _on_loaded(self, v):
        if v is self.view():
            self._side_key = None
            self.sidebar.set_view(v, fresh=True)
            self._sync_panels(v)
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
            if v.doc is not None:
                key = (id(v), v.current_page())
                if key != self._side_key:
                    self._side_key = key
                    self.sidebar.select_page(key[1])
                self.setWindowTitle("%s%s — page %d/%d — %.0f%%" % (
                    "* " if v.modified else "", name, v.current_page() + 1,
                    v.page_count, v.zoom / BASE * 100))
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

    def open_file(self, path):
        real = os.path.realpath(path)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w.path and os.path.realpath(w.path) == real:
                self.tabs.setCurrentIndex(i)
                return
        cur = self.view()
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
        if v is self.view():
            self.mode_actions[v.mode].setChecked(True)
        self._view_changed(v)

    def _save_view(self, v):
        if v.doc is None:
            return False
        if not v.doc.is_pdf:
            QMessageBox.information(self, "Save", "Only PDF files can be saved.")
            return False
        if v.save():
            return True
        QMessageBox.information(
            self, "Save", "This file cannot be updated in place.\n"
            "Choose where to save a copy (pick the same name to replace the original).")
        return self._save_as_view(v)

    def _save_as_view(self, v):
        if v.doc is None or not v.doc.is_pdf:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save as", v.path or "", "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return v.save_as(path)

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
            self.tabs.tabBar().show()
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
        if view.doc is not None:
            text = view.sel_text() if view.sel else ""
            if text:
                m.addAction("Copy text", lambda checked=False: view.copy_selection())
                if view.doc.is_pdf:
                    for kind, label in (("highlight", "Highlight selection"),
                                        ("underline", "Underline selection"),
                                        ("strike", "Strikeout selection")):
                        m.addAction(label, lambda checked=False, k=kind: view.markup_selection(k))
                m.addSeparator()
            page, a = view.annot_under(pos)
            if a is not None:
                if a.type[1] == "Text":
                    m.addAction("Edit note", lambda checked=False: view.edit_note(a))
                m.addAction("Delete annotation", lambda checked=False: view.delete_annot(page, a))
                m.addSeparator()
        for a in (self.a_open, self.a_save, self.a_saveas, None, self.a_find, self.a_bookmark,
                  self.a_goto, self.a_back, self.a_w, self.a_p, self.a_100, None, self.a_fs):
            m.addSeparator() if a is None else m.addAction(a)
        sub = m.addMenu("Panels")
        for a in self.panel_actions.values():
            sub.addAction(a)
        return m

    def closeEvent(self, ev):
        for i in range(self.tabs.count()):
            if not self._confirm(self.tabs.widget(i)):
                ev.ignore()
                return
        for i in range(self.tabs.count()):
            self.tabs.widget(i).modified = False
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
