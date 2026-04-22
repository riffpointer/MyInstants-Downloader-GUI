import os
import threading
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QMenu, QApplication, QInputDialog, QLineEdit, QMessageBox,
    QStackedWidget, QProgressBar
)
from PySide6.QtCore import Signal, Qt, QSize
from .theme import get_icon
from ..utils import target_path_for, sanitize_title

class SoundItemWidget(QFrame):
    play_requested = Signal(dict)
    download_requested = Signal(dict)

    def __init__(self, item, is_downloaded=False, parent_app=None, is_even=False):
        super().__init__()
        self.item = item
        self.parent_app = parent_app
        self.is_selected = False
        self.is_even = is_even
        self.setFrameShape(QFrame.NoFrame)
        
        self.is_dark = False
        if self.parent_app:
            self.is_dark = self.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

        self.update_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.title_label = QLabel(item["title"])
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
        if is_downloaded:
            self.title_label.setStyleSheet(self.title_label.styleSheet() + "color: #22b573;")

        self.btn_play = QPushButton()
        self.btn_play.setIcon(get_icon("play-fill.png", color_invert=self.is_dark))
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setToolTip("Play")
        self.btn_play.setFixedSize(32, 28)
        self.btn_play.setStyleSheet("padding: 2px;")
        self.btn_play.setFocusPolicy(Qt.NoFocus)
        self.btn_play.clicked.connect(lambda: self.play_requested.emit(self.item))
        
        self.btn_download = QPushButton(" Download")
        self.btn_download.setIcon(get_icon("download.png", color_invert=self.is_dark))
        self.btn_download.setIconSize(QSize(14, 14))
        self.btn_download.setStyleSheet("padding: 4px 8px;")
        self.btn_download.setFocusPolicy(Qt.NoFocus)
        self.btn_download.clicked.connect(lambda: self.download_requested.emit(self.item))
        if is_downloaded:
            self.btn_download.setEnabled(False)
            self.btn_download.setText(" Saved")

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(False)
        self.download_progress.setFixedHeight(28)
        self.download_progress.setVisible(False)
        self.download_progress.setStyleSheet(
            "QProgressBar { border: 1px solid rgba(120, 120, 120, 0.35); border-radius: 6px; background: rgba(120, 120, 120, 0.12); }"
            "QProgressBar::chunk { border-radius: 6px; background: #4d9fff; }"
        )

        layout.addWidget(self.btn_play)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.btn_download)
        layout.addWidget(self.download_progress)

    def update_style(self):
        bg_color = "rgba(42, 130, 218, 0.3)" if self.is_selected else ("rgba(255, 255, 255, 0.03)" if (self.is_dark and self.is_even) else "rgba(0, 0, 0, 0.03)" if self.is_even else "transparent")
        self.setStyleSheet(f"SoundItemWidget {{ background-color: {bg_color}; border-radius: 6px; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if hasattr(self.parent_app, "select_item"):
                self.parent_app.select_item(self)
            else:
                self.is_selected = not self.is_selected
                self.update_style()
        super().mousePressEvent(event)

    def set_downloaded(self, downloaded=True):
        if downloaded:
            self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #22b573; background: transparent;")
            self.btn_download.setEnabled(False)
            self.btn_download.setText(" Saved")
            self.btn_download.setVisible(True)
            self.download_progress.setVisible(False)
        else:
            self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
            self.btn_download.setEnabled(True)
            self.btn_download.setText(" Download")
            self.btn_download.setVisible(True)
            self.download_progress.setVisible(False)

    def set_playing(self, playing: bool):
        self.btn_play.setEnabled(not playing)
        self.btn_play.setToolTip("Playing..." if playing else "Play")

    def set_downloading(self, downloading: bool, percent: int = 0):
        self.btn_download.setVisible(not downloading)
        self.download_progress.setVisible(downloading)
        self.download_progress.setValue(max(0, min(100, int(percent))))
        if downloading:
            self.download_progress.setFormat("")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        play_act = menu.addAction("Play")
        play_act.setIcon(get_icon("play-fill.png", color_invert=self.is_dark))
        play_act.triggered.connect(lambda: self.play_requested.emit(self.item))
        
        file_path = target_path_for(self.parent_app.download_dir, self.item["title"])
        if file_path.exists():
            reveal_act = menu.addAction("Reveal in Explorer")
            reveal_act.setIcon(get_icon("folder2-open.png", color_invert=self.is_dark))
            reveal_act.triggered.connect(lambda: os.startfile(str(file_path.parent)))
            
            rename_act = menu.addAction("Rename")
            rename_act.setIcon(get_icon("cursor-text.png", color_invert=self.is_dark))
            rename_act.triggered.connect(lambda: self.parent_app.rename_downloaded_item(file_path))
            
            delete_act = menu.addAction("Delete")
            delete_act.setIcon(get_icon("trash3.png", color_invert=self.is_dark))
            delete_act.triggered.connect(lambda: self.parent_app.delete_downloaded_item(file_path))
        else:
            download_act = menu.addAction("Download")
            download_act.setIcon(get_icon("download.png", color_invert=self.is_dark))
            download_act.triggered.connect(lambda: self.download_requested.emit(self.item))
            
        menu.addSeparator()
        copy_url_act = menu.addAction("Copy URL")
        copy_url_act.setIcon(get_icon("link-45deg.png", color_invert=self.is_dark))
        copy_url_act.triggered.connect(lambda: QApplication.clipboard().setText(self.item["url"]))
        
        menu.exec(event.globalPos())

class InventoryItemWidget(QFrame):
    def __init__(self, file_path, parent_dialog, is_even=False):
        super().__init__()
        self.file_path = file_path
        self.parent_dialog = parent_dialog
        self.is_selected = False
        self.is_even = is_even
        self.setFrameShape(QFrame.NoFrame)
        
        self.is_dark = False
        if hasattr(self.parent_dialog, 'parent_app'):
            self.is_dark = self.parent_dialog.parent_app.settings.get("appearance_mode", "Dark") in ["Dark", "System"]

        self.update_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.stack = QStackedWidget()
        
        self.label = QLabel(file_path.stem)
        self.label.setStyleSheet("font-size: 14px; background: transparent;")
        
        self.edit = QLineEdit(file_path.stem)
        self.edit.setStyleSheet("font-size: 14px;")
        self.edit.editingFinished.connect(self.finish_rename)
        
        self.stack.addWidget(self.label)
        self.stack.addWidget(self.edit)
        layout.addWidget(self.stack, 1)

        btn_play = QPushButton(" Play")
        btn_play.setIcon(get_icon("play-fill.png", color_invert=self.is_dark))
        btn_play.setIconSize(QSize(14, 14))
        btn_play.setStyleSheet("padding: 4px 8px;")
        btn_play.setFocusPolicy(Qt.NoFocus)
        btn_play.clicked.connect(self.play)
        
        btn_rename = QPushButton(" Rename")
        btn_rename.setIcon(get_icon("cursor-text.png", color_invert=self.is_dark))
        btn_rename.setIconSize(QSize(14, 14))
        btn_rename.setStyleSheet("padding: 4px 8px;")
        btn_rename.setFocusPolicy(Qt.NoFocus)
        btn_rename.clicked.connect(self.rename)

        btn_delete = QPushButton(" Delete")
        btn_delete.setIcon(get_icon("trash3.png", color_invert=self.is_dark))
        btn_delete.setIconSize(QSize(14, 14))
        btn_delete.setStyleSheet("padding: 4px 8px;")
        btn_delete.setFocusPolicy(Qt.NoFocus)
        btn_delete.clicked.connect(self.delete)
        
        layout.addWidget(btn_play)
        layout.addWidget(btn_rename)
        layout.addWidget(btn_delete)

    def update_style(self):
        bg_color = "rgba(42, 130, 218, 0.3)" if self.is_selected else ("rgba(255, 255, 255, 0.03)" if (self.is_dark and self.is_even) else "rgba(0, 0, 0, 0.03)" if self.is_even else "transparent")
        self.setStyleSheet(f"InventoryItemWidget {{ background-color: {bg_color}; border-radius: 6px; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if hasattr(self.parent_dialog, "select_item"):
                self.parent_dialog.select_item(self)
            else:
                self.is_selected = not self.is_selected
                self.update_style()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.rename()
        super().mouseDoubleClickEvent(event)

    def play(self):
        threading.Thread(target=self._play_thread, daemon=True).start()

    def _play_thread(self):
        try:
            from playsound import playsound
            playsound(str(self.file_path))
        except Exception as e:
            print(f"Play error: {e}")

    def delete(self):
        if QMessageBox.question(self, "Delete", f"Delete {self.file_path.name}?") == QMessageBox.Yes:
            self.file_path.unlink()
            self.parent_dialog.refresh()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        play_act = menu.addAction("Play")
        play_act.setIcon(get_icon("play-fill.png", color_invert=self.is_dark))
        play_act.triggered.connect(self.play)
        
        reveal_act = menu.addAction("Reveal in Explorer")
        reveal_act.setIcon(get_icon("folder2-open.png", color_invert=self.is_dark))
        reveal_act.triggered.connect(lambda: os.startfile(str(self.file_path.parent)))
        
        rename_act = menu.addAction("Rename")
        rename_act.setIcon(get_icon("cursor-text.png", color_invert=self.is_dark))
        rename_act.triggered.connect(self.rename)
        
        delete_act = menu.addAction("Delete")
        delete_act.setIcon(get_icon("trash3.png", color_invert=self.is_dark))
        delete_act.triggered.connect(self.delete)
        
        menu.addSeparator()
        copy_path_act = menu.addAction("Copy Path")
        copy_path_act.setIcon(get_icon("link-45deg.png", color_invert=self.is_dark))
        copy_path_act.triggered.connect(lambda: QApplication.clipboard().setText(str(self.file_path.resolve())))
        
        menu.exec(event.globalPos())

    def rename(self):
        self.stack.setCurrentIndex(1)
        self.edit.setText(self.file_path.stem)
        self.edit.setFocus()
        self.edit.selectAll()

    def finish_rename(self):
        self.stack.setCurrentIndex(0)
        new_name = self.edit.text().strip()
        if new_name and new_name != self.file_path.stem:
            new_path = self.file_path.with_name(f"{sanitize_title(new_name)}.mp3")
            if not new_path.exists():
                self.file_path.rename(new_path)
                self.file_path = new_path
                self.label.setText(self.file_path.stem)
            else:
                QMessageBox.warning(self, "Rename", "File already exists.")
                self.edit.setText(self.file_path.stem)
