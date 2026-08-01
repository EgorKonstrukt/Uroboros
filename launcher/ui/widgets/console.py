import re
import time
import threading
from collections import deque

from PyQt6.QtCore import Qt, QTimer, QRegularExpression
from PyQt6.QtGui import (
    QColor, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor,
    QTextDocument, QTextFormat,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QToolButton,
    QLineEdit, QComboBox, QLabel, QCheckBox,
)


# ── ANSI (16-color) ──
_ANSI_FG = {
    30: "#7A7A7A", 31: "#F06262", 32: "#7ED687", 33: "#F7C566",
    34: "#6FA8DC", 35: "#C58CD9", 36: "#6FB5B5", 37: "#E6E6E6",
    90: "#9E9E9E", 91: "#FF8A8A", 92: "#A5E8B0", 93: "#FFE0A0",
    94: "#93C6F5", 95: "#E0B0F0", 96: "#9ADADA", 97: "#FFFFFF",
}

# ── Minecraft legacy color codes ──
_MC_COLORS = {
    "0": "#000000", "1": "#0000AA", "2": "#00AA00", "3": "#00AAAA",
    "4": "#AA0000", "5": "#AA00AA", "6": "#FFAA00", "7": "#AAAAAA",
    "8": "#555555", "9": "#5555FF", "a": "#55FF55", "b": "#55FFFF",
    "c": "#FF5555", "d": "#FF55FF", "e": "#FFFF55", "f": "#FFFFFF",
}

_LEVEL_COLORS = {
    "error": "#FF6B6B",
    "warn": "#FFD479",
    "debug": "#8C8C8C",
}
_CHAT_NAME_COLOR = "#55FFFF"
_TIMESTAMP_COLOR = "#7A7A7A"

_CHAT_RE = re.compile(r"^<([^>]{1,32})>")
_LEVEL_ERR_RE = re.compile(r"\b(?:ERROR|SEVERE|FATAL|CRITICAL|EXCEPTION)\b|Exception in thread|\*\*\* ERROR")
_LEVEL_WARN_RE = re.compile(r"\b(?:WARN|WARNING)\b")
_LEVEL_DEBUG_RE = re.compile(r"\bDEBUG\b")

_MATCH_BG = QColor(255, 214, 90, 110)
_CURRENT_BG = QColor(255, 170, 0, 170)


def _classify(text: str) -> str:
    if _CHAT_RE.match(text):
        return "chat"
    if _LEVEL_ERR_RE.search(text):
        return "error"
    if _LEVEL_WARN_RE.search(text):
        return "warn"
    if _LEVEL_DEBUG_RE.search(text):
        return "debug"
    return "info"


def _parse_rich(text: str, base: str) -> list:
    """Parse ANSI + Minecraft § codes into (fg, bold, underline, italic, text) spans."""
    segs = []
    buf = []
    fg = base
    bold = False
    underline = False
    italic = False

    def flush():
        nonlocal buf
        if buf:
            segs.append((fg, bold, underline, italic, "".join(buf)))
            buf = []

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\u00a7" and i + 1 < n:
            code = text[i + 1].lower()
            flush()
            if code in _MC_COLORS:
                fg = _MC_COLORS[code]
                bold = False
                underline = False
                italic = False
            elif code == "l":
                bold = True
            elif code == "n":
                underline = True
            elif code == "o":
                italic = True
            elif code == "r":
                fg = base
                bold = False
                underline = False
                italic = False
            i += 2
            continue
        if ch == "\x1b" and i + 1 < n:
            if text[i + 1] == "[":
                j = text.find("m", i + 2)
                if j != -1:
                    flush()
                    for c in text[i + 2:j].split(";"):
                        try:
                            num = int(c.strip())
                        except ValueError:
                            continue
                        if num == 0:
                            fg = base; bold = False; underline = False; italic = False
                        elif num == 1:
                            bold = True
                        elif num == 3:
                            italic = True
                        elif num == 4:
                            underline = True
                        elif num == 22:
                            bold = False
                        elif num == 23:
                            italic = False
                        elif num == 24:
                            underline = False
                        elif num in _ANSI_FG:
                            fg = _ANSI_FG[num]
                    i = j + 1
                    continue
            elif text[i + 1] == "]":
                # OSC sequence (\x1b]...;...) -> strip until BEL or ESC backslash
                j = i + 2
                while j < n and text[j] != "\x07" and not (text[j] == "\x1b" and j + 1 < n and text[j + 1] == "\\"):
                    j += 1
                if j < n:
                    i = j + 1
                    continue
        buf.append(ch)
        i += 1
    flush()
    if not segs:
        segs = [(base, False, False, False, text)]
    return segs


class ConsoleWidget(QWidget):
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._max_lines = 8000
        self._lines = []
        self._queue = deque()
        self._lock = threading.Lock()
        self._needs_rebuild = False

        self._font_size = getattr(config, "console_font_size", 12) if config else 12
        self._word_wrap = getattr(config, "console_word_wrap", False) if config else False
        self._timestamps = getattr(config, "console_timestamps", False) if config else False
        self._follow = getattr(config, "console_follow", True) if config else True
        self._level_filter = "all"
        self._regex = False
        self._match_count = 0

        self._setup_ui()
        self._apply_font_size()
        self._apply_wrap()
        self._load_state_buttons()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(40)
        self._flush_timer.timeout.connect(self._drain)
        self._flush_timer.start()

        self._install_shortcuts()

    # ── UI ──

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.follow_btn = self._make_toggle("Follow", self._toggle_follow)
        toolbar.addWidget(self.follow_btn)

        self.time_btn = self._make_toggle("Time", self._toggle_timestamps)
        toolbar.addWidget(self.time_btn)

        self.wrap_btn = self._make_toggle("Wrap", self._toggle_wrap)
        toolbar.addWidget(self.wrap_btn)

        zoom_out = QToolButton(self)
        zoom_out.setObjectName("ConsoleToolButton")
        zoom_out.setText("\u2212")
        zoom_out.setToolTip("Zoom out (Ctrl+-)")
        zoom_out.clicked.connect(lambda: self._zoom(-1))
        toolbar.addWidget(zoom_out)

        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setObjectName("ConsoleStatus")
        toolbar.addWidget(self.zoom_label)

        zoom_in = QToolButton(self)
        zoom_in.setObjectName("ConsoleToolButton")
        zoom_in.setText("+")
        zoom_in.setToolTip("Zoom in (Ctrl+=)")
        zoom_in.clicked.connect(lambda: self._zoom(1))
        toolbar.addWidget(zoom_in)

        self.search_btn = self._make_toggle("Search", self._toggle_search)
        toolbar.addWidget(self.search_btn)

        toolbar.addStretch()

        self.level_combo = QComboBox(self)
        self.level_combo.setObjectName("ConsoleLevelFilter")
        self.level_combo.addItem("All levels", "all")
        self.level_combo.addItem("Errors only", "error")
        self.level_combo.addItem("Warnings + errors", "warn")
        self.level_combo.addItem("Debug and above", "debug")
        self.level_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.level_combo)

        self.clear_btn = QPushButton("Clear", self)
        self.clear_btn.setObjectName("ConsoleClearButton")
        self.clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(self.clear_btn)

        layout.addLayout(toolbar)

        self.search_row = QWidget(self)
        sr_layout = QHBoxLayout(self.search_row)
        sr_layout.setContentsMargins(0, 0, 0, 0)
        sr_layout.setSpacing(6)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("ConsoleSearch")
        self.search_input.setPlaceholderText("Search \u2026 (Ctrl+F)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._find_next)
        sr_layout.addWidget(self.search_input, 1)

        self.regex_check = QCheckBox("Regex", self)
        self.regex_check.setObjectName("ConsoleRegex")
        self.regex_check.toggled.connect(self._on_search_changed)
        sr_layout.addWidget(self.regex_check)

        self.match_label = QLabel("", self)
        self.match_label.setObjectName("ConsoleStatus")
        self.match_label.setMinimumWidth(56)
        sr_layout.addWidget(self.match_label)

        prev_btn = QToolButton(self)
        prev_btn.setObjectName("ConsoleNavButton")
        prev_btn.setText("\u25b2")
        prev_btn.setToolTip("Previous match (Shift+Enter)")
        prev_btn.clicked.connect(self._find_prev)
        sr_layout.addWidget(prev_btn)

        next_btn = QToolButton(self)
        next_btn.setObjectName("ConsoleNavButton")
        next_btn.setText("\u25bc")
        next_btn.setToolTip("Next match (Enter)")
        next_btn.clicked.connect(self._find_next)
        sr_layout.addWidget(next_btn)

        close_btn = QToolButton(self)
        close_btn.setObjectName("ConsoleNavButton")
        close_btn.setText("\u2715")
        close_btn.setToolTip("Close search (Esc)")
        close_btn.clicked.connect(lambda: self._toggle_search(False))
        sr_layout.addWidget(close_btn)

        self.search_row.setVisible(False)
        layout.addWidget(self.search_row)

        self.output = QTextEdit(self)
        self.output.setObjectName("ConsoleOutput")
        self.output.setReadOnly(True)
        self.output.setFrameShape(QTextEdit.Shape.NoFrame)

        layout.addWidget(self.output, 1)

        self.status_label = QLabel("Lines: 0", self)
        self.status_label.setObjectName("ConsoleStatus")
        status_row = QHBoxLayout()
        status_row.addStretch()
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)

    def _make_toggle(self, text, slot):
        btn = QToolButton(self)
        btn.setObjectName("ConsoleToolButton")
        btn.setText(text)
        btn.setCheckable(True)
        btn.clicked.connect(slot)
        return btn

    def _load_state_buttons(self):
        self.follow_btn.setChecked(self._follow)
        self.time_btn.setChecked(self._timestamps)
        self.wrap_btn.setChecked(self._word_wrap)

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+L"), self, self.clear)
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self._zoom(1))
        QShortcut(QKeySequence("Ctrl++"), self, lambda: self._zoom(1))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self._zoom(-1))
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self._zoom(0))
        QShortcut(QKeySequence("Escape"), self, self._on_escape)

    # ── Public API (thread-safe) ──

    def append(self, text: str):
        with self._lock:
            self._queue.append(text)

    def clear(self):
        with self._lock:
            self._queue.clear()
        self._lines = []
        self._needs_rebuild = False
        self.output.clear()
        self._match_count = 0
        self._update_status()

    # ── Plumbing ──

    def _drain(self):
        with self._lock:
            if not self._queue:
                return
            batch = list(self._queue)
            self._queue.clear()
        for text in batch:
            self._add_line(text)
        if self._needs_rebuild:
            self._needs_rebuild = False
            self._render_all()
        else:
            self._update_status()
        if self._follow:
            self._scroll_to_bottom()
        if self.search_input.text() or self._match_count:
            self._highlight_matches()

    def _add_line(self, text: str):
        text = text.rstrip("\r\n")
        line = {"text": text, "level": _classify(text), "ts": time.time()}
        self._lines.append(line)
        visible = self._passes_filter(line["level"])
        if len(self._lines) > self._max_lines:
            self._lines.pop(0)
            if self._level_filter == "all":
                self._trim_first_block()
            else:
                self._needs_rebuild = True
        if visible and not self._needs_rebuild:
            self._append_to_doc(line)

    def _append_to_doc(self, line: dict):
        doc = self.output.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not doc.isEmpty():
            cursor.insertBlock()
        self._insert_line(cursor, line)

    def _insert_line(self, cursor: QTextCursor, line: dict):
        if self._timestamps:
            ts = time.strftime("[%H:%M:%S] ", time.localtime(line["ts"]))
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_TIMESTAMP_COLOR))
            cursor.insertText(ts, fmt)
        for fg, bold, underline, italic, text in self._segments(line):
            if not text:
                continue
            fmt = QTextCharFormat()
            if fg:
                fmt.setForeground(QColor(fg))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if underline:
                fmt.setFontUnderline(True)
            if italic:
                fmt.setFontItalic(True)
            cursor.insertText(text, fmt)

    def _segments(self, line: dict):
        text = line["text"]
        level = line["level"]
        base = _LEVEL_COLORS.get(level)
        if level == "chat":
            m = _CHAT_RE.match(text)
            if m:
                segs = [(_CHAT_NAME_COLOR, False, False, False, m.group(0))]
                segs.extend(_parse_rich(text[m.end():], None))
                return segs
        return _parse_rich(text, base)

    def _trim_first_block(self):
        doc = self.output.document()
        if doc.blockCount() <= 1:
            return
        block = doc.firstBlock()
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.deleteChar()

    def _passes_filter(self, level: str) -> bool:
        f = self._level_filter
        if f == "all":
            return True
        if f == "error":
            return level == "error"
        if f == "warn":
            return level in ("warn", "error")
        if f == "debug":
            return level in ("debug", "info", "chat", "warn", "error")
        return True

    def _visible_lines(self):
        if self._level_filter == "all":
            return list(self._lines)
        return [ln for ln in self._lines if self._passes_filter(ln["level"])]

    def _render_all(self):
        self.output.clear()
        cursor = QTextCursor(self.output.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        first = True
        for line in self._visible_lines():
            if not first:
                cursor.insertBlock()
            first = False
            self._insert_line(cursor, line)
        if self._follow:
            self._scroll_to_bottom()
        self._update_status()
        self._highlight_matches()

    def _scroll_to_bottom(self):
        sb = self.output.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    # ── Toolbar actions ──

    def _toggle_follow(self, checked):
        self._follow = bool(checked)
        if self._follow:
            self._scroll_to_bottom()
        self._save_settings()

    def _toggle_timestamps(self, checked):
        self._timestamps = bool(checked)
        self._render_all()
        self._save_settings()

    def _toggle_wrap(self, checked):
        self._word_wrap = bool(checked)
        self._apply_wrap()
        self._save_settings()

    def _toggle_search(self, visible=None):
        show = self.search_row.isHidden() if visible is None else visible
        self.search_row.setVisible(show)
        if show:
            self.search_input.setFocus()
        else:
            self.search_input.clear()
            self.output.setFocus()
            self._highlight_matches()

    def _focus_search(self):
        self.search_row.setVisible(True)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_escape(self):
        if not self.search_row.isHidden():
            self._toggle_search(False)
            return
        if self.output.hasFocus():
            self.output.clearFocus()

    def _zoom(self, delta: int):
        if delta == 0:
            self._font_size = 12
        else:
            self._font_size = max(8, min(26, self._font_size + delta))
        self._apply_font_size()
        self._save_settings()

    def _apply_font_size(self):
        self.output.setStyleSheet(f"font-size: {self._font_size}px;")
        self.zoom_label.setText(f"{self._font_size}px")

    def _apply_wrap(self):
        self.output.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if self._word_wrap else QTextEdit.LineWrapMode.NoWrap
        )

    def _save_settings(self):
        if not self.config:
            return
        self.config.console_font_size = self._font_size
        self.config.console_word_wrap = self._word_wrap
        self.config.console_timestamps = self._timestamps
        self.config.console_follow = self._follow
        self.config.save()

    # ── Filtering ──

    def _on_filter_changed(self, _index):
        self._level_filter = self.level_combo.currentData()
        self._render_all()

    # ── Search ──

    def _on_search_changed(self, _text=""):
        self._highlight_matches()

    def _search_regex(self):
        q = self.search_input.text()
        if not q:
            return None
        try:
            if self.regex_check.isChecked():
                return re.compile(q, re.IGNORECASE)
            return re.compile(re.escape(q), re.IGNORECASE)
        except re.error:
            return None

    def _highlight_matches(self):
        rx = self._search_regex()
        selections = []
        count = 0
        if rx:
            block = self.output.document().firstBlock()
            while block.isValid():
                for m in rx.finditer(block.text()):
                    sel = QTextEdit.ExtraSelection()
                    sel.format.setBackground(_MATCH_BG)
                    sel.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
                    cur = QTextCursor(block)
                    cur.setPosition(block.position() + m.start(), QTextCursor.MoveMode.MoveAnchor)
                    cur.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
                    sel.cursor = cur
                    selections.append(sel)
                block = block.next()
            count = len(selections)
            if count:
                current = QTextEdit.ExtraSelection()
                current.format.setBackground(_CURRENT_BG)
                current.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
                current.cursor = self.output.textCursor()
                selections.append(current)
        self._match_count = count
        self.output.setExtraSelections(selections)
        self.match_label.setText(f"{count}" if rx else "")
        self._update_status()

    def _find_next(self):
        q = self.search_input.text()
        if not q:
            return
        flags = QTextDocument.FindFlag(0)
        if self.regex_check.isChecked():
            found = self.output.find(QRegularExpression(q), flags)
            if not found:
                cur = QTextCursor(self.output.document())
                cur.movePosition(QTextCursor.MoveOperation.Start)
                self.output.setTextCursor(cur)
                self.output.find(QRegularExpression(q), flags)
        else:
            found = self.output.find(q, flags)
            if not found:
                cur = QTextCursor(self.output.document())
                cur.movePosition(QTextCursor.MoveOperation.Start)
                self.output.setTextCursor(cur)
                self.output.find(q, flags)
        self._highlight_matches()

    def _find_prev(self):
        q = self.search_input.text()
        if not q:
            return
        flags = QTextDocument.FindFlag.FindBackward
        if self.regex_check.isChecked():
            found = self.output.find(QRegularExpression(q), flags)
            if not found:
                cur = QTextCursor(self.output.document())
                cur.movePosition(QTextCursor.MoveOperation.End)
                self.output.setTextCursor(cur)
                self.output.find(QRegularExpression(q), flags)
        else:
            found = self.output.find(q, flags)
            if not found:
                cur = QTextCursor(self.output.document())
                cur.movePosition(QTextCursor.MoveOperation.End)
                self.output.setTextCursor(cur)
                self.output.find(q, flags)
        self._highlight_matches()

    def _update_status(self):
        shown = self.output.document().blockCount()
        parts = [f"Lines: {len(self._lines)}", f"Shown: {shown}"]
        if self._match_count:
            parts.append(f"Matches: {self._match_count}")
        self.status_label.setText(" \u00b7 ".join(parts))
