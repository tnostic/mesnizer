import os
import copy
import shutil
import time
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QSpinBox, 
    QTabWidget, QCheckBox, QFileDialog, QTextEdit, QMessageBox, QInputDialog,
    QWidget, QGroupBox, QFormLayout, QScrollArea, QFrame
)
from PySide6.QtGui import QIcon, QAction, QTextCursor, QFont, QPixmap, QColor, QPalette
from PySide6.QtCore import QTimer, QThread, Signal, Qt, QObject

appName = "Mesnizer"
configFile = "config.json"
logFile = "organizer.log"

def getDefaultConfig():
    defaultConfigPath = "config.json"
    if os.path.exists(defaultConfigPath):
        with open(defaultConfigPath, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {
            "source_folder": str(Path.home() / "Downloads"),
            "organize_by_date": False,
            "default_interval_minutes": 60,
            "file_categories": {
                "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".heic"],
                "Videos": [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm", ".m4v"],
                "Documents": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"],
                "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"],
                "Scripts": [".py", ".js", ".html", ".css", ".php", ".java", ".cpp", ".c", ".h", ".cs", ".rb", ".go", ".json", ".xml"],
                "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
                "Executables": [".exe", ".msi", ".app", ".bat", ".sh", ".apk"]
            },
            "ignored_items": ["desktop.ini", "thumbs.db", ".DS_Store", "Mesnizer", "organizer.log"]
        }

class OrganizerWorker(QThread):
    logSignal = Signal(str, str)
    finishedSignal = Signal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.stopRequested = False

    def run(self):
        sourceDir = Path(self.config.get('source_folder', getDefaultConfig()['source_folder']))
        if not sourceDir.exists():
            self.logSignal.emit("ERROR", f"Source directory not found: {sourceDir}")
            return

        ignored = set(self.config.get('ignored_items', []))
        categories = self.config.get('file_categories', {})
        useDate = self.config.get('organize_by_date', False)

        extMap = {}
        for cat, exts in categories.items():
            for ext in exts:
                extMap[ext.lower()] = cat

        self.logSignal.emit("INFO", f"Scanning {sourceDir}...")

        for item in sourceDir.iterdir():
            if self.stopRequested:
                break

            if item.name in ignored or item.name.startswith('.'):
                continue

            category = "Misc"
            if item.is_file():
                category = extMap.get(item.suffix.lower(), "Misc")
            elif item.is_dir():
                if item.name in categories.keys() or item.name in ["Misc", "Folders"]:
                    continue
                category = "Folders"

            destFolder = sourceDir / category
            
            if useDate and item.is_file():
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                destFolder = destFolder / str(mtime.year) / f"{mtime.month:02d}"

            try:
                destFolder.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.logSignal.emit("ERROR", f"Failed to create dir {destFolder}: {e}")
                continue

            target = destFolder / item.name
            target = self._getUniquePath(target)

            if target.resolve() == item.resolve():
                continue

            try:
                shutil.move(str(item), str(target))
                self.logSignal.emit("INFO", f"Moved: {item.name} -> {category}")
            except Exception as e:
                self.logSignal.emit("ERROR", f"Failed to move {item.name}: {e}")

        self.finishedSignal.emit()

    def _getUniquePath(self, path: Path) -> Path:
        if not path.exists():
            return path
        
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        
        while True:
            if path.is_dir():
                newName = f"{stem}_{counter}" 
            else:
                newName = f"{stem}_{counter}{suffix}"
            
            newPath = parent / newName
            if not newPath.exists():
                return newPath
            counter += 1

class ConfigDialog(QDialog):
    def __init__(self, configData, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure {appName}")
        self.resize(800, 600)
        self.setMinimumSize(700, 500)
        self.config = copy.deepcopy(configData)
        self.setWindowIcon(QIcon("tray_icon.ico"))
        
        mainLayout = QVBoxLayout(self)
        mainLayout.setContentsMargins(10, 10, 10, 10)
        mainLayout.setSpacing(10)
        
        self.tabs = QTabWidget()
        mainLayout.addWidget(self.tabs)
        
        tabGeneral = QWidget()
        genLayout = QVBoxLayout(tabGeneral)
        genLayout.setContentsMargins(10, 10, 10, 10)
        genLayout.setSpacing(15)
        
        srcGroup = QGroupBox("Source Folder")
        srcGroupLayout = QHBoxLayout(srcGroup)
        self.srcInput = QLineEdit(self.config.get('source_folder', ''))
        self.srcInput.setReadOnly(True)
        btnBrowse = QPushButton("Browse...")
        btnBrowse.clicked.connect(self.browseFolder)
        srcGroupLayout.addWidget(self.srcInput)
        srcGroupLayout.addWidget(btnBrowse)
        genLayout.addWidget(srcGroup)
        
        settingsGroup = QGroupBox("Settings")
        settingsLayout = QFormLayout(settingsGroup)
        
        self.spinInterval = QSpinBox()
        self.spinInterval.setRange(1, 1440)
        self.spinInterval.setValue(self.config.get('default_interval_minutes', 60))
        settingsLayout.addRow("Scan Interval (minutes):", self.spinInterval)
        
        self.chkDate = QCheckBox("Organize into Date Subfolders (Year/Month)")
        self.chkDate.setChecked(self.config.get('organize_by_date', False))
        settingsLayout.addRow(self.chkDate)
        
        genLayout.addWidget(settingsGroup)
        genLayout.addStretch()
        self.tabs.addTab(tabGeneral, "General")
        
        tabCats = QWidget()
        catLayout = QVBoxLayout(tabCats)
        catLayout.setContentsMargins(10, 10, 10, 10)
        catLayout.setSpacing(10)
        
        instructions = QLabel("Manage file categories and their associated extensions. "
                              "Each category will become a subfolder in the destination directory.")
        instructions.setWordWrap(True)
        instructions.setStyleSheet("QLabel { color: #555; }")
        catLayout.addWidget(instructions)
        
        listContainer = QWidget()
        listLayout = QHBoxLayout(listContainer)
        
        self.listCats = QListWidget()
        self.refreshCatList()
        listLayout.addWidget(self.listCats)
        
        btnLayout = QVBoxLayout()
        btnAddCat = QPushButton("Add Category")
        btnDelCat = QPushButton("Remove Category")
        btnEditCat = QPushButton("Edit Extensions")
        
        btnAddCat.clicked.connect(self.addCategory)
        btnDelCat.clicked.connect(self.removeCategory)
        btnEditCat.clicked.connect(self.editCategory)
        
        btnLayout.addWidget(btnAddCat)
        btnLayout.addWidget(btnDelCat)
        btnLayout.addWidget(btnEditCat)
        btnLayout.addStretch()
        listLayout.addLayout(btnLayout)
        
        catLayout.addWidget(listContainer)
        catLayout.addStretch()
        self.tabs.addTab(tabCats, "Categories")
        
        tabIgnore = QWidget()
        ignLayout = QVBoxLayout(tabIgnore)
        ignLayout.setContentsMargins(10, 10, 10, 10)
        ignLayout.setSpacing(10)
        
        ignInstructions = QLabel("List of files/folders to ignore during organization. "
                                "Add items like temporary files, metadata files, or your application folder.")
        ignInstructions.setWordWrap(True)
        ignInstructions.setStyleSheet("QLabel { color: #555; }")
        ignLayout.addWidget(ignInstructions)
        
        ignListContainer = QWidget()
        ignListLayout = QHBoxLayout(ignListContainer)
        
        self.listIgnore = QListWidget()
        for item in self.config.get('ignored_items', []):
            self.listIgnore.addItem(item)
        ignListLayout.addWidget(self.listIgnore)
        
        ignBtnLayout = QVBoxLayout()
        btnAddIgn = QPushButton("Add Item")
        btnDelIgn = QPushButton("Remove Item")
        
        btnAddIgn.clicked.connect(self.addIgnored)
        btnDelIgn.clicked.connect(self.removeIgnored)
        
        ignBtnLayout.addWidget(btnAddIgn)
        ignBtnLayout.addWidget(btnDelIgn)
        ignBtnLayout.addStretch()
        ignListLayout.addLayout(ignBtnLayout)
        
        ignLayout.addWidget(ignListContainer)
        ignLayout.addStretch()
        self.tabs.addTab(tabIgnore, "Ignored Items")
        
        tabLogs = QWidget()
        logLayout = QVBoxLayout(tabLogs)
        logLayout.setContentsMargins(10, 10, 10, 10)
        logLayout.setSpacing(10)
        
        logInstructions = QLabel("Application logs showing recent organization activities and errors.")
        logInstructions.setWordWrap(True)
        logInstructions.setStyleSheet("QLabel { color: #555; }")
        logLayout.addWidget(logInstructions)

        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollContent = QWidget()
        scrollLayout = QVBoxLayout(scrollContent)
        
        self.txtLog = QTextEdit()
        self.txtLog.setReadOnly(True)
        self.txtLog.setFont(QFont("Consolas", 9))
        self.loadLogs()
        scrollLayout.addWidget(self.txtLog)
        scrollArea.setWidget(scrollContent)
        logLayout.addWidget(scrollArea)
        
        btnRefreshLog = QPushButton("Refresh Logs")
        btnRefreshLog.clicked.connect(self.loadLogs)
        logLayout.addWidget(btnRefreshLog)
        self.tabs.addTab(tabLogs, "Logs")

        footer = QHBoxLayout()
        footer.addStretch()
        
        btnSave = QPushButton("Save Settings")
        btnCancel = QPushButton("Cancel")
        
        btnSave.setDefault(True)
        btnSave.clicked.connect(self.saveConfig)
        btnCancel.clicked.connect(self.reject)
        
        footer.addWidget(btnSave)
        footer.addWidget(btnCancel)
        mainLayout.addLayout(footer)

        self.applyStyles()

    def applyStyles(self):
        try: 
            with open('themes.qss', 'r', encoding='utf-8') as f:
                stylesheetContent = f.read()
            self.setStyleSheet(stylesheetContent)
        except FileNotFoundError:
            print("Warning: styles.qss not found.")
            self.setStyleSheet("")

    def browseFolder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Organize", self.srcInput.text())
        if folder:
            self.srcInput.setText(folder)

    def refreshCatList(self):
        self.listCats.clear()
        for cat, exts in self.config['file_categories'].items():
            item = QListWidgetItem(f"{cat} ({len(exts)} extensions)")
            item.setData(Qt.UserRole, cat)
            self.listCats.addItem(item)

    def addCategory(self):
        name, ok = QInputDialog.getText(self, "New Category", "Category Name:")
        if ok and name:
            if name not in self.config['file_categories']:
                self.config['file_categories'][name] = []
                self.refreshCatList()
            else:
                QMessageBox.warning(self, "Error", "Category already exists.")

    def removeCategory(self):
        row = self.listCats.currentRow()
        if row >= 0:
            catName = self.listCats.item(row).data(Qt.UserRole)
            del self.config['file_categories'][catName]
            self.refreshCatList()

    def editCategory(self):
        row = self.listCats.currentRow()
        if row < 0: return
        
        catName = self.listCats.item(row).data(Qt.UserRole)
        currentExts = ", ".join(self.config['file_categories'][catName])
        
        text, ok = QInputDialog.getMultiLineText(self, "Edit Extensions", 
                                               f"Extensions for {catName} (comma separated):", 
                                               currentExts)
        if ok:
            rawList = [x.strip() for x in text.split(',') if x.strip()]
            cleanList = []
            for ext in rawList:
                if not ext.startswith('.'): ext = '.' + ext
                cleanList.append(ext)
            
            self.config['file_categories'][catName] = cleanList
            self.refreshCatList()

    def addIgnored(self):
        name, ok = QInputDialog.getText(self, "Ignore Item", "File/Folder name to ignore:")
        if ok and name:
            self.listIgnore.addItem(name)

    def removeIgnored(self):
        row = self.listIgnore.currentRow()
        if row >= 0:
            self.listIgnore.takeItem(row)

    def loadLogs(self):
        if os.path.exists(logFile):
            with open(logFile, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-1000:]
                self.txtLog.setPlainText("".join(lines))
                self.txtLog.moveCursor(QTextCursor.End)
        else:
            self.txtLog.setPlainText("No logs found.")

    def saveConfig(self):
        self.config['source_folder'] = self.srcInput.text()
        self.config['default_interval_minutes'] = self.spinInterval.value()
        self.config['organize_by_date'] = self.chkDate.isChecked()
        
        ignored = []
        for i in range(self.listIgnore.count()):
            ignored.append(self.listIgnore.item(i).text())
        self.config['ignored_items'] = ignored
        
        self.accept()

class SystemTrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(logFile, encoding='utf-8'), logging.StreamHandler()]
        )
        
        self.loadConfig()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.runOrganizer)
        
        self.worker = None
        
        self.setupUi()
        
        self.updateTimer()
        
        if not os.path.exists(configFile):
            self.showConfig()
        
        logging.info("Mesnizer Started")

    

    def loadConfig(self):
        try:
            with open(configFile, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            defaultConfig = getDefaultConfig()
            for k, v in defaultConfig.items():
                if k not in self.config:
                    self.config[k] = v
        except FileNotFoundError:
            self.config = getDefaultConfig()
            self.saveConfig()

    def saveConfig(self):
        with open(configFile, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)
        self.updateTimer()

    def updateTimer(self):
        interval = self.config.get('default_interval_minutes', 60) * 60 * 1000
        self.timer.start(interval)

    def setupUi(self):
        self.tray = QSystemTrayIcon()
        iconPath = "tray_icon.ico"
        self.tray.setIcon(QIcon(iconPath))
            
        menu = QMenu()
        
        actionSort = QAction("Sort Now", self.app)
        actionSort.triggered.connect(self.runOrganizer)
        menu.addAction(actionSort)
        
        menu.addSeparator()
        
        actionConfig = QAction("Configure", self.app)
        actionConfig.triggered.connect(self.showConfig)
        menu.addAction(actionConfig)
        
        actionExit = QAction("Exit", self.app)
        actionExit.triggered.connect(self.app.quit)
        menu.addAction(actionExit)
        
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{appName} - Running")
        self.tray.show()

    def showConfig(self):
        dialog = ConfigDialog(self.config)
        if dialog.exec() == QDialog.Accepted:
            self.config = dialog.config
            self.saveConfig()
            logging.info("Configuration updated.")

    def runOrganizer(self):
        if self.worker and self.worker.isRunning():
            logging.warning("Organizer is already running.")
            return
            
        self.tray.setToolTip(f"{appName} - Sorting...")
        
        self.worker = OrganizerWorker(self.config)
        self.worker.logSignal.connect(self.handleLog)
        self.worker.finishedSignal.connect(self.onWorkerFinished)
        self.worker.start()

    def handleLog(self, level, msg):
        if level == "ERROR":
            logging.error(msg)
        else:
            logging.info(msg)

    def onWorkerFinished(self):
        self.tray.setToolTip(f"{appName} - Idle")
        self.tray.showMessage(appName, "Organization complete.", QSystemTrayIcon.Information, 2000)

    def run(self):
        return self.app.exec()

if __name__ == "__main__":
    app = SystemTrayApp()
    sys.exit(app.run())
