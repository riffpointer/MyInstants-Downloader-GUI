from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QTextEdit, QPushButton, 
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QTimer
from time import perf_counter
from .widgets import InventoryItemWidget
from ..workers.download_worker import DownloadWorker
from ..utils import format_speed, target_path_for, ensure_directory
from ..settings import save_settings
from ..constants import DEFAULT_REGION, DEFAULT_BASE_URL

class BatchDownloadDialog(QDialog):
    def __init__(self, parent, items, download_dir):
        super().__init__(parent)
        self.parent_app = parent
        self.items = items
        self.download_dir = download_dir
        self.is_cancelled = False
        self.current_worker = None
        self.workers = []
        self.total_items = len(self.items)
        self.completed_items = 0
        self.batch_start_time = perf_counter()
        
        self.setWindowTitle("Batch Download")
        self.resize(600, 400)
        self.setup_ui()
        
        QTimer.singleShot(100, self.start_next)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.label_overall = QLabel(f"Preparing to download {self.total_items} files...")
        layout.addWidget(self.label_overall)
        
        self.progress_overall = QProgressBar()
        self.progress_overall.setMaximum(self.total_items)
        layout.addWidget(self.progress_overall)
        
        self.label_current = QLabel("Waiting...")
        layout.addWidget(self.label_current)
        
        self.progress_current = QProgressBar()
        layout.addWidget(self.progress_current)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel)
        layout.addWidget(self.btn_cancel)

    def start_next(self):
        if not self.items or self.is_cancelled:
            self.label_overall.setText(f"Batch download complete ({self.completed_items}/{self.total_items}).")
            self.btn_cancel.setText("Close")
            
            if self.parent_app.settings.get("auto_download_next_page", False) and not self.is_cancelled:
                self.accept()
            return
            
        item = self.items.pop(0)
        self.label_current.setText(f"Downloading: {item['title']} (0 B/s)")
        self.log_view.append(f"Starting: {item['title']}")
        
        self.current_worker = DownloadWorker(item, self.download_dir)
        self.workers.append(self.current_worker)
        self.current_worker.signals.progress.connect(self.update_progress)
        self.current_worker.signals.finished.connect(self.on_finished)
        self.current_worker.signals.error.connect(self.on_error)
        self.current_worker.start()

    def update_progress(self, data):
        self.progress_current.setValue(int(data['percent'] * 100))
        if self.current_worker:
            self.label_current.setText(f"Downloading: {self.current_worker.item['title']} ({format_speed(data['speed'])})")

    def update_overall_label(self):
        elapsed = max(perf_counter() - self.batch_start_time, 0.001)
        speed = self.completed_items / elapsed
        self.label_overall.setText(f"Downloaded {self.completed_items} of {self.total_items} files ({speed:.1f} items/sec)")

    def on_finished(self, msg):
        self.log_view.append(msg)
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def on_error(self, err):
        self.log_view.append(f"Error: {err}")
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def cancel(self):
        self.is_cancelled = True
        if self.current_worker:
            self.current_worker.is_cancelled = True
        self.accept()

class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Settings")
        self.resize(500, 400)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Download Directory
        layout.addWidget(QLabel("Download Directory:"))
        h_layout = QHBoxLayout()
        self.edit_dir = QLineEdit(self.parent_app.settings["download_dir"])
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_dir)
        h_layout.addWidget(self.edit_dir)
        h_layout.addWidget(btn_browse)
        layout.addLayout(h_layout)
        
        # Theme
        layout.addWidget(QLabel("Appearance Mode:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Dark", "Light", "System"])
        self.combo_theme.setCurrentText(self.parent_app.settings.get("appearance_mode", "Dark"))
        layout.addWidget(self.combo_theme)
        
        # Region
        layout.addWidget(QLabel("Server Region:"))
        self.edit_region = QLineEdit(self.parent_app.settings.get("server_region", DEFAULT_REGION))
        layout.addWidget(self.edit_region)
        
        # Base URL
        layout.addWidget(QLabel("Server Base URL:"))
        self.edit_url = QLineEdit(self.parent_app.settings.get("server_base_url", DEFAULT_BASE_URL))
        layout.addWidget(self.edit_url)
        
        # Hide Downloaded
        self.check_hide = QCheckBox("Hide Downloaded Sounds")
        self.check_hide.setChecked(self.parent_app.settings.get("hide_downloaded", True))
        layout.addWidget(self.check_hide)

        # Auto Download Next Page
        self.check_auto_download = QCheckBox("Auto-Download Next Page (after Batch Download)")
        self.check_auto_download.setChecked(self.parent_app.settings.get("auto_download_next_page", False))
        layout.addWidget(self.check_auto_download)
        
        layout.addStretch()
        
        btns = QHBoxLayout()
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edit_dir.text())
        if path:
            self.edit_dir.setText(path)

    def save(self):
        self.parent_app.settings["download_dir"] = self.edit_dir.text()
        self.parent_app.settings["appearance_mode"] = self.combo_theme.currentText()
        self.parent_app.settings["server_region"] = self.edit_region.text()
        self.parent_app.settings["server_base_url"] = self.edit_url.text()
        self.parent_app.settings["hide_downloaded"] = self.check_hide.isChecked()
        self.parent_app.settings["auto_download_next_page"] = self.check_auto_download.isChecked()
        
        save_settings(self.parent_app.settings)
        self.parent_app.apply_settings()
        self.accept()

class InventoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Inventory")
        self.resize(800, 600)
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Directory Controls
        from .theme import get_icon
        is_dark = self.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
        
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Download Directory:"))
        self.edit_dir = QLineEdit(str(self.parent_app.download_dir))
        self.edit_dir.setReadOnly(True)
        dir_layout.addWidget(self.edit_dir)
        
        btn_browse = QPushButton(" Browse")
        btn_browse.setIcon(get_icon("folder2-open.png", color_invert=is_dark))
        btn_browse.setStyleSheet("padding: 4px 8px;")
        btn_browse.clicked.connect(self.browse_dir)
        dir_layout.addWidget(btn_browse)
        
        btn_open = QPushButton(" Open Downloads")
        btn_open.setIcon(get_icon("folder2-open.png", color_invert=is_dark))
        btn_open.setStyleSheet("padding: 4px 8px;")
        import os
        btn_open.clicked.connect(lambda: os.startfile(str(self.parent_app.download_dir)))
        dir_layout.addWidget(btn_open)
        
        layout.addLayout(dir_layout)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        
        layout.addWidget(self.scroll)

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edit_dir.text())
        if path:
            self.edit_dir.setText(path)
            self.parent_app.settings["download_dir"] = path
            save_settings(self.parent_app.settings)
            self.parent_app.apply_settings()
            self.refresh()

    def refresh(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
            
        files = sorted(self.parent_app.download_dir.glob("*.mp3"))
        if not files:
            from .theme import get_icon
            is_dark = self.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]
            
            empty_icon = QLabel()
            empty_icon.setPixmap(get_icon("box2-fill.png", color_invert=is_dark).pixmap(64, 64))
            empty_icon.setAlignment(Qt.AlignCenter)
            
            empty_label = QLabel("No items in inventory")
            empty_label.setStyleSheet("font-size: 16px; color: #888;")
            empty_label.setAlignment(Qt.AlignCenter)
            
            self.list_layout.addStretch()
            self.list_layout.addWidget(empty_icon)
            self.list_layout.addWidget(empty_label)
            self.list_layout.addStretch()
        else:
            for i, f in enumerate(files):
                self.list_layout.addWidget(InventoryItemWidget(f, self, is_even=(i % 2 == 0)))

class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("About")
        self.resize(300, 200)
        self.setup_ui(parent)

    def setup_ui(self, parent):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)

        from .theme import get_icon
        is_dark = parent.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

        icon_label = QLabel()
        icon_label.setPixmap(get_icon("flush.png", color_invert=is_dark).pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel("MyInstants Downloader")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        desc_label = QLabel("A simple and clean downloader for MyInstants.\nBuilt with PySide6.")
        desc_label.setStyleSheet("font-size: 14px; color: #888;")
        desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_label)

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
