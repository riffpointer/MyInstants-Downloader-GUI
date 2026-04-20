import os
import threading
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QScrollArea, QFrame, QMessageBox, QMenu, QApplication, QInputDialog,
    QStackedWidget, QProgressBar
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt

from .theme import get_icon, apply_dark_theme, apply_light_theme
from .widgets import SoundItemWidget
from .dialogs import BatchDownloadDialog, SettingsDialog, InventoryDialog, AboutDialog
from ..constants import APP_TITLE, DEFAULT_REGION, DEFAULT_BASE_URL
from ..settings import load_settings, save_settings
from ..utils import ensure_directory, target_path_for, sanitize_title
from ..workers.scrape_worker import ScrapeWorker
from ..workers.download_worker import DownloadWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.download_dir = Path(self.settings["download_dir"]).expanduser()
        ensure_directory(self.download_dir)
        
        self.current_page = 1
        self.current_items = []
        self.active_workers = []
        self.selected_widget = None
        
        self.setup_ui()
        self.setup_menu()
        self.apply_settings()
        self.load_page(1)

    def setup_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        self.setWindowIcon(get_icon("main.ico"))
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Toolbar
        self.toolbar = QFrame()
        self.toolbar.setFrameShape(QFrame.NoFrame)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        
        self.btn_download_all = QPushButton(" Download All")
        self.btn_download_all.setStyleSheet("padding: 4px 8px;")
        self.btn_download_all.clicked.connect(self.download_all)
        
        self.btn_inventory = QPushButton(" Inventory")
        self.btn_inventory.setStyleSheet("padding: 4px 8px;")
        self.btn_inventory.clicked.connect(self.open_inventory)
        
        self.toolbar_layout.addWidget(self.btn_download_all)
        self.toolbar_layout.addWidget(self.btn_inventory)
        
        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton(" Prev")
        self.btn_prev.setStyleSheet("padding: 4px 8px;")
        self.btn_prev.clicked.connect(self.prev_page)
        self.page_label = QLabel("Page 1")
        self.btn_next = QPushButton(" Next")
        self.btn_next.setStyleSheet("padding: 4px 8px;")
        self.btn_next.clicked.connect(self.next_page)
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.page_label)
        self.nav_layout.addWidget(self.btn_next)
        self.toolbar_layout.addLayout(self.nav_layout)
        
        self.toolbar_layout.addStretch()
        
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search sounds...")
        search_icon = get_icon("search.png", color_invert=is_dark)
        self.search_entry.addAction(search_icon, QLineEdit.LeadingPosition)
        self.search_entry.returnPressed.connect(self.search)
        self.btn_search = QPushButton(" Search")
        self.btn_search.setStyleSheet("padding: 4px 8px;")
        self.btn_search.clicked.connect(self.search)
        
        self.toolbar_layout.addWidget(self.search_entry)
        self.toolbar_layout.addWidget(self.btn_search)
        
        self.layout.addWidget(self.toolbar)
        
        # Main List Area
        self.stacked_widget = QStackedWidget()
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.list_layout.setSpacing(5)
        self.scroll_area.setWidget(self.list_container)
        
        self.stacked_widget.addWidget(self.scroll_area)
        
        # Loading View
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)
        
        self.loading_label = QLabel("Loading...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 16px; color: #888;")
        
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0) # Indeterminate
        self.loading_progress.setFixedWidth(200)
        
        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(self.loading_progress)
        
        self.stacked_widget.addWidget(self.loading_widget)
        
        self.layout.addWidget(self.stacked_widget)
        
        # Status bar
        self.statusBar().showMessage("Ready")

    def setup_menu(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("&File")
        act_download_all = file_menu.addAction("Download All Current")
        act_download_all.triggered.connect(self.download_all)
        act_inventory = file_menu.addAction("Inventory")
        act_inventory.triggered.connect(self.open_inventory)
        act_settings = file_menu.addAction("Settings")
        act_settings.triggered.connect(self.open_settings)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("Exit")
        act_exit.triggered.connect(self.close)

        navigate_menu = menubar.addMenu("&Navigate")
        act_trending = navigate_menu.addAction("Back To Trending")
        act_trending.triggered.connect(lambda: self.load_page(1))
        navigate_menu.addSeparator()
        act_prev = navigate_menu.addAction("Previous Page")
        act_prev.triggered.connect(self.prev_page)
        act_next = navigate_menu.addAction("Next Page")
        act_next.triggered.connect(self.next_page)
        navigate_menu.addSeparator()
        act_reload = navigate_menu.addAction("Reload Current View")
        act_reload.triggered.connect(self.reload_current_view)

        view_menu = menubar.addMenu("&View")
        act_dark = view_menu.addAction("Dark Theme")
        act_dark.triggered.connect(lambda: self.set_theme("Dark"))
        act_light = view_menu.addAction("Light Theme")
        act_light.triggered.connect(lambda: self.set_theme("Light"))
        act_system = view_menu.addAction("System Theme")
        act_system.triggered.connect(lambda: self.set_theme("System"))

        help_menu = menubar.addMenu("&Help")
        act_about = help_menu.addAction("About")
        act_about.triggered.connect(self.open_about)

    def apply_settings(self):
        self.download_dir = Path(self.settings["download_dir"]).expanduser()
        ensure_directory(self.download_dir)
        self.set_theme(self.settings.get("appearance_mode", "Dark"), persist=False)

    def set_theme(self, mode, persist=True):
        self.settings["appearance_mode"] = mode
        if persist:
            save_settings(self.settings)
        
        is_dark = mode == "Dark"
        if mode == "System":
            # Just a simplification, could use a library to detect system theme
            is_dark = True 
            
        if is_dark:
            apply_dark_theme(QApplication.instance())
        else:
            apply_light_theme(QApplication.instance())
            
        self.update_icons(is_dark)
        self.render_items(self.current_items)

    def update_icons(self, is_dark):
        self.setWindowIcon(get_icon("main.ico"))
        self.btn_download_all.setIcon(get_icon("download.png", color_invert=is_dark))
        self.btn_inventory.setIcon(get_icon("box2-fill.png", color_invert=is_dark))
        self.btn_prev.setIcon(get_icon("arrow-left.png", color_invert=is_dark))
        self.btn_next.setIcon(get_icon("arrow-right.png", color_invert=is_dark))
        self.btn_search.setIcon(get_icon("search.png", color_invert=is_dark))

    def load_page(self, page_number):
        self.statusBar().showMessage(f"Loading page {page_number}...")
        self.current_page = page_number
        self.page_label.setText(f"Page {page_number}")
        
        self.stacked_widget.setCurrentWidget(self.loading_widget)
        
        worker = ScrapeWorker('page', str(page_number), 
                              region=self.settings.get("server_region", DEFAULT_REGION),
                              base_url=self.settings.get("server_base_url", DEFAULT_BASE_URL))
        worker.signals.finished.connect(self.on_items_loaded)
        worker.signals.error.connect(self.on_error)
        worker.start()
        self.active_workers.append(worker)

    def search(self):
        query = self.search_entry.text().strip()
        if not query: return
        
        self.statusBar().showMessage(f"Searching for '{query}'...")
        self.stacked_widget.setCurrentWidget(self.loading_widget)
        
        worker = ScrapeWorker('search', query,
                              base_url=self.settings.get("server_base_url", DEFAULT_BASE_URL))
        worker.signals.finished.connect(self.on_items_loaded)
        worker.signals.error.connect(self.on_error)
        worker.start()
        self.active_workers.append(worker)

    def on_items_loaded(self, items):
        self.current_items = items
        self.selected_widget = None
        self.statusBar().showMessage(f"Loaded {len(items)} sounds.")
        self.render_items(items)
        self.stacked_widget.setCurrentWidget(self.scroll_area)
        
        if getattr(self, "is_auto_downloading", False):
            if items:
                QTimer.singleShot(500, self.download_all)
            else:
                self.is_auto_downloading = False
                self.statusBar().showMessage("Auto-download finished (no more items).")

    def on_error(self, error_msg):
        self.statusBar().showMessage(f"Error: {error_msg}")
        self.stacked_widget.setCurrentWidget(self.scroll_area)
        self.is_auto_downloading = False
        QMessageBox.critical(self, "Error", error_msg)

    def render_items(self, items):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        
        hide_downloaded = self.settings.get("hide_downloaded", True)
        for i, item in enumerate(items):
            is_downloaded = target_path_for(self.download_dir, item["title"]).exists()
            if hide_downloaded and is_downloaded:
                continue
            widget = SoundItemWidget(item, is_downloaded, parent_app=self, is_even=(i % 2 == 0))
            widget.play_requested.connect(self.play_sound)
            widget.download_requested.connect(self.download_item)
            self.list_layout.addWidget(widget)

    def select_item(self, widget):
        if self.selected_widget:
            self.selected_widget.is_selected = False
            self.selected_widget.update_style()
        
        self.selected_widget = widget
        if self.selected_widget:
            self.selected_widget.is_selected = True
            self.selected_widget.update_style()
            self.scroll_area.ensureWidgetVisible(self.selected_widget)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            widgets = []
            for i in range(self.list_layout.count()):
                w = self.list_layout.itemAt(i).widget()
                if isinstance(w, SoundItemWidget):
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

    def play_sound(self, item):
        self.statusBar().showMessage(f"Playing: {item['title']}")
        threading.Thread(target=self._play_thread, args=(item['url'],), daemon=True).start()

    def _play_thread(self, url):
        try:
            from playsound import playsound
            playsound(url)
        except Exception as e:
            print(f"Play error: {e}")

    def download_item(self, item):
        self.statusBar().showMessage(f"Downloading: {item['title']}...")
        worker = DownloadWorker(item, self.download_dir)
        worker.signals.finished.connect(lambda msg: self.statusBar().showMessage(msg))
        worker.signals.finished.connect(self.refresh_item_states)
        worker.signals.error.connect(self.on_error)
        worker.start()
        self.active_workers.append(worker)

    def download_all(self):
        if not self.current_items:
            self.is_auto_downloading = False
            return
            
        selected_items = []
        all_shown_items = []
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, SoundItemWidget) and widget.btn_download.isEnabled():
                all_shown_items.append(widget.item)
                if widget.is_selected:
                    selected_items.append(widget.item)

        items_to_download = selected_items if selected_items else all_shown_items

        if not items_to_download:
            self.is_auto_downloading = False
            return

        dialog = BatchDownloadDialog(self, items_to_download, self.download_dir)
        dialog.exec()
        self.refresh_item_states()

        if self.settings.get("auto_download_next_page", False) and not dialog.is_cancelled:
            self.is_auto_downloading = True
            import random
            delay = random.randint(5000, 10000)
            self.statusBar().showMessage(f"Auto-downloading next page in {delay//1000} seconds...")
            QTimer.singleShot(delay, self.next_page)
        else:
            self.is_auto_downloading = False

    def open_inventory(self):
        dialog = InventoryDialog(self)
        dialog.exec()
        self.refresh_item_states()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.apply_settings()

    def open_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def reload_current_view(self):
        self.load_page(self.current_page)

    def refresh_item_states(self):
        if self.settings.get("hide_downloaded", True):
            self.render_items(self.current_items)
        else:
            for i in range(self.list_layout.count()):
                widget = self.list_layout.itemAt(i).widget()
                if isinstance(widget, SoundItemWidget):
                    is_downloaded = target_path_for(self.download_dir, widget.item["title"]).exists()
                    widget.set_downloaded(is_downloaded)

    def rename_downloaded_item(self, file_path):
        new_name, ok = QInputDialog.getText(self, "Rename", "Enter new name:", QLineEdit.Normal, file_path.stem)
        if ok and new_name:
            new_path = file_path.with_name(f"{sanitize_title(new_name)}.mp3")
            if not new_path.exists():
                file_path.rename(new_path)
                self.refresh_item_states()
            else:
                QMessageBox.warning(self, "Rename", "File already exists.")

    def delete_downloaded_item(self, file_path):
        if QMessageBox.question(self, "Delete", f"Delete {file_path.name}?") == QMessageBox.Yes:
            file_path.unlink()
            self.refresh_item_states()

    def next_page(self):
        self.load_page(self.current_page + 1)

    def prev_page(self):
        if self.current_page > 1:
            self.load_page(self.current_page - 1)
