#!/usr/bin/env python3
"""Polkit Explorer 2.1 — with tag/value explanations + Ctrl-C handling"""

import sys
import signal
from pathlib import Path
from lxml import etree
from PySide6 import QtCore, QtGui, QtWidgets

# ──────────────────────────────────────────────────────────────────────────────
#  OPTIONAL DARK / LIGHT STYLESHEET
# ──────────────────────────────────────────────────────────────────────────────
try:
    import qdarktheme
    _HAVE_DARKTHEME = True
except ImportError:
    _HAVE_DARKTHEME = False

# ──────────────────────────────────────────────────────────────────────────────
#  HUMAN-READABLE DESCRIPTIONS  (from polkit(8) + pklocalauthority(8))
# ──────────────────────────────────────────────────────────────────────────────
TAG_DESCS = {
    "allow_any":      "Implicit authorization that applies to <i>all</i> subjects "
                      "regardless of whether they have an active or inactive session.",
    "allow_inactive": "Authorization that applies only to subjects in an <i>inactive</i> "
                      "session (e.g. a remote SSH login).",
    "allow_active":   "Authorization that applies only to subjects in an <i>active</i> "
                      "local session (physically at the console).",
}

VALUE_DESCS = {
    "yes":              "Action is allowed without further authentication.",
    "no":               "Action is always denied.",
    "auth_self":        "The <b>local user</b> must authenticate (e.g. enter password).",
    "auth_self_keep":   "Same as <code>auth_self</code> but the authentication is kept\n"
                        "for a short period (≈ 5 min) for the <i>same&nbsp;process</i>.",
    "auth_admin":       "An <b>administrator</b> (member of the admin group) must authenticate.",
    "auth_admin_keep":  "Like <code>auth_admin</code> but the privilege is cached "
                        "for a few minutes for the same process.",
}

# ──────────────────────────────────────────────────────────────────────────────
class PolicyModel(QtGui.QStandardItemModel):
    """A one-column tree model listing <action id=""> nodes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Action ID"])

    def load(self, policy_path: str):
        self.clear()
        self.setHorizontalHeaderLabels(["Action ID"])
        parser = etree.XMLParser(encoding="utf-8")
        root = etree.parse(policy_path, parser).getroot()

        for action in root.iter("action"):
            act_id = action.get("id")
            if act_id:
                item = QtGui.QStandardItem(act_id)
                item.setEditable(False)
                item.setData(action, QtCore.Qt.UserRole)
                self.appendRow(item)

# ──────────────────────────────────────────────────────────────────────────────
class Explorer(QtWidgets.QMainWindow):
    SETTINGS_ORG = "PolkitExplorer"
    SETTINGS_APP = "Explorer2"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polkit Explorer 2.1")
        self.resize(960, 600)
        self.settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        self._build_ui()
        self._build_menubar()
        if _HAVE_DARKTHEME:
            self._apply_theme()

        self.statusBar().showMessage("Ready")

    # ─────────────────────────────── UI ───────────────────────────────
    def _build_ui(self):
        # left: filter + tree --------------------------------------------------
        self.filterEdit = QtWidgets.QLineEdit(placeholderText="Filter actions…")
        self.tree       = QtWidgets.QTreeView(alternatingRowColors=True)
        self.tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        self.model = PolicyModel(self)
        self.proxy = QtCore.QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.tree.setModel(self.proxy)

        self.filterEdit.textChanged.connect(self.proxy.setFilterFixedString)
        self.tree.selectionModel().selectionChanged.connect(
            self._on_action_selected)

        left = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(left)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self.filterEdit)
        vbox.addWidget(self.tree)

        # right: description + defaults table + explanation -------------------
        self.descLabel = QtWidgets.QLabel(wordWrap=True,
                                          alignment=QtCore.Qt.AlignTop)
        self.descLabel.setMinimumHeight(60)

        self.defaults = QtWidgets.QTableWidget(0, 2)
        self.defaults.setHorizontalHeaderLabels(["Tag", "Value"])
        self.defaults.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.defaults.verticalHeader().setVisible(False)
        self.defaults.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.defaults.itemSelectionChanged.connect(
            self._on_default_row_selected)

        self.explLabel = QtWidgets.QLabel(wordWrap=True,
                                          alignment=QtCore.Qt.AlignTop)
        self.explLabel.setStyleSheet("margin-top:4px; color: #4a4a4a;")

        right = QtWidgets.QWidget()
        rv    = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.addWidget(QtWidgets.QLabel("Description:"))
        rv.addWidget(self.descLabel)
        rv.addSpacing(8)
        rv.addWidget(QtWidgets.QLabel("Defaults:"))
        rv.addWidget(self.defaults, 1)
        rv.addWidget(QtWidgets.QLabel("Explanation:"))
        rv.addWidget(self.explLabel)

        # final splitter ------------------------------------------------------
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

    # ───────────────────────────── Menus ──────────────────────────────
    def _build_menubar(self):
        mb        = self.menuBar()
        file_menu = mb.addMenu("&File")

        open_act = QtGui.QAction(QtGui.QIcon.fromTheme("document-open"),
                                 "&Open…", self, shortcut=QtGui.QKeySequence.Open,
                                 triggered=self.open_file)
        file_menu.addAction(open_act)

        self.recent_menu = file_menu.addMenu("Open &Recent")
        self._populate_recent()

        file_menu.addSeparator()
        file_menu.addAction(QtGui.QAction("&Quit", self,
                                          shortcut=QtGui.QKeySequence.Quit,
                                          triggered=self.close))

        help_menu = mb.addMenu("&Help")
        help_menu.addAction(QtGui.QAction("&About", self,
                                          triggered=self._show_about))

    # ─────────────────────────── Slots ────────────────────────────────
    def open_file(self, checked: bool = False, path: str | None = None):
        """Slot for File→Open and for Recent-file actions."""
        if isinstance(checked, str) and path is None:     # called via lambda
            path, checked = checked, False

        if path is None or isinstance(path, bool):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Open PolicyKit file",
                "/usr/share/polkit-1/actions/", "*.policy")
            if not path:
                return

        self._load_policy(path)
        self._add_recent(path)

    def _load_policy(self, policy_path: str):
        self.model.load(policy_path)
        self.tree.expandAll()
        self.filterEdit.clear()
        self.statusBar().showMessage(
            f"Loaded {Path(policy_path).name} "
            f"({self.model.rowCount()} actions)", 5000)

    # ----- selecting an action ↴
    def _on_action_selected(self, selected, _ignored):
        if not selected.indexes():
            return
        idx       = selected.indexes()[0]
        src_idx   = self.proxy.mapToSource(idx)
        action_el = src_idx.data(QtCore.Qt.UserRole)

        locale = QtCore.QLocale.system().name().replace('_', '-')
        ns     = {"xml": "http://www.w3.org/XML/1998/namespace"}
        nodes  = action_el.xpath(f"./description[@xml:lang='{locale}']",
                                 namespaces=ns)
        desc_el = nodes[0] if nodes else (
            action_el.find("description") or action_el.find("_description"))

        self.descLabel.setText(
            desc_el.text.strip() if desc_el is not None and desc_el.text
            else "«no description»")

        # populate defaults table
        self.defaults.setRowCount(0)
        defaults_el = action_el.find("defaults")
        if defaults_el is not None:
            for child in defaults_el:
                r = self.defaults.rowCount()
                self.defaults.insertRow(r)
                self.defaults.setItem(r, 0, QtWidgets.QTableWidgetItem(child.tag))
                self.defaults.setItem(r, 1, QtWidgets.QTableWidgetItem(child.text or ""))

        self.explLabel.clear()

    # ----- selecting a row in Defaults ↴
    def _on_default_row_selected(self):
        row = self.defaults.currentRow()
        if row == -1:
            self.explLabel.clear()
            return
        tag   = self.defaults.item(row, 0).text()
        value = self.defaults.item(row, 1).text()

        tag_expl   = TAG_DESCS.get(tag,   "No description available.")
        value_expl = VALUE_DESCS.get(value, "No description available.")

        self.explLabel.setText(
            f"<b>{tag}</b>: {tag_expl}<br><b>{value}</b>: {value_expl}")

    # ───────────────────────── Recent files ───────────────────────────
    MAX_RECENT = 5

    def _add_recent(self, path: str):
        recents = self.settings.value("recent", [], type=list)
        path    = str(Path(path).resolve())
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self.settings.setValue("recent", recents[:self.MAX_RECENT])
        self._populate_recent()

    def _populate_recent(self):
        self.recent_menu.clear()
        recents = self.settings.value("recent", [], type=list)
        if not recents:
            self.recent_menu.addAction(QtGui.QAction("(none)", self,
                                                     enabled=False))
        else:
            for p in recents:
                act = QtGui.QAction(Path(p).name, self,
                                    triggered=lambda _, p=p: self.open_file(p))
                self.recent_menu.addAction(act)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction(
            QtGui.QAction("Clear list", self,
                          triggered=lambda: self.settings.remove("recent")))

    # ────────────────────────── Helpers ───────────────────────────────
    def _show_about(self):
        QtWidgets.QMessageBox.about(
            self, "About Polkit Explorer 2.1",
            "GUI viewer for PolicyKit .policy files\n\n"
            "• Explainer panel for tags/values\n"
            "• CTRL-C to quit gracefully\n"
            "© 2013-2025  Kevin Cave & contributors")

    def _apply_theme(self):
        luminance = QtWidgets.QApplication.palette().color(
            QtGui.QPalette.Window).value()
        mode = "dark" if luminance < 128 else "light"
        self.setStyleSheet(qdarktheme.load_stylesheet(mode))

# ─────────────────────────────── main ────────────────────────────────
def main():
    # allow Ctrl-C to kill even when the Qt window has focus
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName(Explorer.SETTINGS_ORG)
    app.setApplicationName(Explorer.SETTINGS_APP)

    win = Explorer()
    win.show()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        # graceful CLI exit (e.g. running under a debugger or plain terminal)
        print("\nInterrupted — bye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
