from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QTextEdit, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QScrollArea, QWidget, QSpinBox,
    QStackedWidget
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
        self.active_workers = []
        
        # Concurrency setting
        self.max_concurrent = self._get_max_concurrent()
        self.use_concurrent = self.max_concurrent > 1
        
        self.worker_progress_map = {} # worker -> progress_bar
        
        self.total_items = len(self.items)
        self.completed_items = 0
        self.batch_start_time = perf_counter()
        
        self.setWindowTitle("Batch Download")
        self.resize(600, 500 if self.use_concurrent else 400)
        self.setup_ui()
        
        QTimer.singleShot(100, self.start_next)

    def _get_max_concurrent(self):
        raw_value = self.parent_app.settings.get("concurrent_downloads", 5)
        if isinstance(raw_value, bool):
            raw_value = 5 if raw_value else 1
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(5, value))

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.label_overall = QLabel(f"Preparing to download {self.total_items} files...")
        layout.addWidget(self.label_overall)
        
        self.progress_overall = QProgressBar()
        self.progress_overall.setMaximum(self.total_items)
        layout.addWidget(self.progress_overall)
        
        self.label_status = QLabel("Active downloads: 0")
        layout.addWidget(self.label_status)

        # Individual progress bars
        self.sub_progress_container = QWidget()
        self.sub_progress_layout = QVBoxLayout(self.sub_progress_container)
        self.sub_progress_layout.setContentsMargins(0, 0, 0, 0)
        self.sub_progress_layout.setSpacing(2)
        
        self.sub_bars = []
        num_bars = self.max_concurrent
        for i in range(num_bars):
            bar_widget = QWidget()
            bar_layout = QVBoxLayout(bar_widget)
            bar_layout.setContentsMargins(0, 2, 0, 2)
            bar_layout.setSpacing(0)
            
            label = QLabel("Idle")
            label.setStyleSheet("font-size: 11px; color: #888;")
            bar = QProgressBar()
            bar.setFixedHeight(12 if self.use_concurrent else 18)
            bar.setTextVisible(False)
            
            bar_layout.addWidget(label)
            bar_layout.addWidget(bar)
            
            self.sub_progress_layout.addWidget(bar_widget)
            self.sub_bars.append({"widget": bar_widget, "label": label, "bar": bar, "in_use": False})
            
        layout.addWidget(self.sub_progress_container)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(150)
        layout.addWidget(self.log_view)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel)
        layout.addWidget(self.btn_cancel)

    def start_next(self):
        if self.is_cancelled:
            return

        while len(self.active_workers) < self.max_concurrent and self.items:
            # Find an available bar
            available_bar = None
            for b in self.sub_bars:
                if not b["in_use"]:
                    available_bar = b
                    break
            
            if not available_bar:
                break
                
            item = self.items.pop(0)
            self.log_view.append(f"Starting: {item['title']}")
            
            available_bar["in_use"] = True
            available_bar["label"].setText(f"Downloading: {item['title']}")
            available_bar["bar"].setValue(0)
            
            worker = DownloadWorker(item, self.download_dir)
            self.active_workers.append(worker)
            self.worker_progress_map[worker] = available_bar
            
            worker.signals.progress.connect(lambda data, w=worker: self.update_sub_progress(data, w))
            worker.signals.finished.connect(lambda msg, w=worker: self.on_finished(msg, w))
            worker.signals.error.connect(lambda err, w=worker: self.on_error(err, w))
            worker.start()

        self.update_status_label()

        if not self.items and not self.active_workers:
            self.label_overall.setText(f"Batch download complete ({self.completed_items}/{self.total_items}).")
            self.btn_cancel.setText("Close")
            if self.parent_app.settings.get("auto_download_next_page", False) and not self.is_cancelled:
                self.accept()

    def update_sub_progress(self, data, worker):
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map[worker]
            bar_info["bar"].setValue(int(data['percent'] * 100))
            bar_info["label"].setText(f"Downloading: {worker.item['title']} ({format_speed(data['speed'])})")

    def update_status_label(self):
        self.label_status.setText(f"Active downloads: {len(self.active_workers)} | Remaining in queue: {len(self.items)}")

    def update_overall_label(self):
        elapsed = max(perf_counter() - self.batch_start_time, 0.001)
        speed = self.completed_items / elapsed
        self.label_overall.setText(f"Downloaded {self.completed_items} of {self.total_items} files ({speed:.1f} items/sec)")

    def on_finished(self, msg, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map.pop(worker)
            bar_info["in_use"] = False
            bar_info["label"].setText("Idle")
            bar_info["bar"].setValue(0)
            
        self.log_view.append(msg)
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def on_error(self, err, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
            
        if worker in self.worker_progress_map:
            bar_info = self.worker_progress_map.pop(worker)
            bar_info["in_use"] = False
            bar_info["label"].setText("Idle")
            bar_info["bar"].setValue(0)
            
        self.log_view.append(f"Error: {err}")
        self.completed_items += 1
        self.progress_overall.setValue(self.completed_items)
        self.update_overall_label()
        self.start_next()

    def cancel(self):
        self.is_cancelled = True
        for worker in self.active_workers:
            worker.is_cancelled = True
        self.accept()

class AutoNextPageDialog(QDialog):
    def __init__(self, parent, delay_ms, on_timeout):
        super().__init__(parent)
        self.setWindowTitle("Auto-Download Next Page")
        self.setModal(False)
        self.delay_ms = max(0, int(delay_ms))
        self.remaining_ms = self.delay_ms
        self.on_timeout = on_timeout
        self.has_triggered = False

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

        self._setup_ui()
        self._update_label()
        self.timer.start()

    def _setup_ui(self):
        self.resize(520, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(self.label)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(self.btn_cancel, alignment=Qt.AlignCenter)

    def _seconds_remaining(self):
        return max(0, (self.remaining_ms + 999) // 1000)

    def _update_label(self):
        seconds = self._seconds_remaining()
        self.label.setText(f"Downloading next page in {seconds} seconds...")

    def _tick(self):
        self.remaining_ms = max(0, self.remaining_ms - self.timer.interval())
        self._update_label()
        if self.remaining_ms <= 0:
            self._trigger_timeout()

    def _trigger_timeout(self):
        if self.has_triggered:
            return
        self.has_triggered = True
        self.timer.stop()
        self.hide()
        if self.on_timeout:
            self.on_timeout()
        self.accept()

    def reject(self):
        self.timer.stop()
        super().reject()

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

        # Concurrent Downloads
        current_concurrent = self.parent_app.settings.get("concurrent_downloads", 5)
        if isinstance(current_concurrent, bool):
            current_concurrent = 5 if current_concurrent else 0
        try:
            current_concurrent = int(current_concurrent)
        except (TypeError, ValueError):
            current_concurrent = 5
        current_concurrent = max(0, min(5, current_concurrent))

        self.check_concurrent = QCheckBox("Enable Concurrent Downloads")
        self.check_concurrent.setChecked(current_concurrent > 0)
        layout.addWidget(self.check_concurrent)

        concurrent_row = QHBoxLayout()
        self.label_concurrent = QLabel("Workers:")
        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(0, 5)
        self.spin_concurrent.setValue(current_concurrent or 5)
        self.spin_concurrent.setEnabled(self.check_concurrent.isChecked())
        concurrent_row.addWidget(self.label_concurrent)
        concurrent_row.addWidget(self.spin_concurrent)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        self.check_concurrent.toggled.connect(self._toggle_concurrent_controls)
        self._toggle_concurrent_controls(self.check_concurrent.isChecked())
        
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

    def _toggle_concurrent_controls(self, enabled):
        self.label_concurrent.setVisible(enabled)
        self.spin_concurrent.setVisible(enabled)
        self.spin_concurrent.setEnabled(enabled)

    def save(self):
        self.parent_app.settings["download_dir"] = self.edit_dir.text()
        self.parent_app.settings["appearance_mode"] = self.combo_theme.currentText()
        self.parent_app.settings["server_region"] = self.edit_region.text()
        self.parent_app.settings["server_base_url"] = self.edit_url.text()
        self.parent_app.settings["hide_downloaded"] = self.check_hide.isChecked()
        self.parent_app.settings["auto_download_next_page"] = self.check_auto_download.isChecked()
        self.parent_app.settings["concurrent_downloads"] = (
            self.spin_concurrent.value() if self.check_concurrent.isChecked() else 0
        )
        
        save_settings(self.parent_app.settings)
        self.parent_app.apply_settings()
        self.accept()

class InventoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Inventory")
        self.resize(800, 600)
        self.selected_widget = None
        self.setup_ui()
        QTimer.singleShot(0, self.load_inventory)

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
        btn_browse.setFocusPolicy(Qt.NoFocus)
        btn_browse.setAutoDefault(False)
        btn_browse.setDefault(False)
        btn_browse.clicked.connect(self.browse_dir)
        dir_layout.addWidget(btn_browse)
        
        btn_open = QPushButton(" Open Downloads")
        btn_open.setIcon(get_icon("folder2-open.png", color_invert=is_dark))
        btn_open.setStyleSheet("padding: 4px 8px;")
        btn_open.setFocusPolicy(Qt.NoFocus)
        btn_open.setAutoDefault(False)
        btn_open.setDefault(False)
        import os
        btn_open.clicked.connect(lambda: os.startfile(str(self.parent_app.download_dir)))
        dir_layout.addWidget(btn_open)
        
        layout.addLayout(dir_layout)
        
        self.stacked = QStackedWidget()

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)

        self.loading_label = QLabel("Loading inventory...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 16px; color: #888;")

        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setFixedWidth(200)

        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(self.loading_progress)

        self.stacked.addWidget(self.loading_widget)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        self.stacked.addWidget(self.scroll)

        layout.addWidget(self.stacked)
        self.stacked.setCurrentWidget(self.loading_widget)

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edit_dir.text())
        if path:
            self.edit_dir.setText(path)
            self.parent_app.settings["download_dir"] = path
            save_settings(self.parent_app.settings)
            self.parent_app.apply_settings()
            self.load_inventory()

    def load_inventory(self):
        self.stacked.setCurrentWidget(self.loading_widget)
        QTimer.singleShot(0, self._populate_inventory)

    def _populate_inventory(self):
        self.selected_widget = None
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

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
        self.stacked.setCurrentWidget(self.scroll)

    def refresh(self):
        self.load_inventory()

    def select_item(self, widget):
        if self.selected_widget:
            self.selected_widget.is_selected = False
            self.selected_widget.update_style()
        
        self.selected_widget = widget
        if self.selected_widget:
            self.selected_widget.is_selected = True
            self.selected_widget.update_style()
            self.scroll.ensureWidgetVisible(self.selected_widget)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            widgets = []
            for i in range(self.list_layout.count()):
                w = self.list_layout.itemAt(i).widget()
                if isinstance(w, InventoryItemWidget):
                    widgets.append(w)
            
            if not widgets:
                return super().keyPressEvent(event)
            
            if self.selected_widget is None:
                self.select_item(widgets[0])
            else:
                try:
                    current_idx = widgets.index(self.selected_widget)
                    if event.key() == Qt.Key_Up:
                        new_idx = max(0, current_idx - 1)
                    else:
                        new_idx = min(len(widgets) - 1, current_idx + 1)
                    self.select_item(widgets[new_idx])
                except ValueError:
                    self.select_item(widgets[0])
            return
            
        super().keyPressEvent(event)

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
