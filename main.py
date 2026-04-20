from pathlib import Path
from time import perf_counter
from PIL import Image, ImageOps
from playsound import playsound
import customtkinter
from bsoup_test import DEFAULT_BASE_URL, DEFAULT_REGION, getPage, normalize_base_url, normalize_region, searchq
import requests
import threading
import os
import re
import tkinter
import json
from tkinter import filedialog, messagebox, simpledialog


customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("blue")

APP_TITLE = "MyInstants Downloader and Player"
APP_SETTINGS_FILE = Path("settings.json")
DEFAULT_DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_CHUNK_SIZE = 4096
VIRTUAL_ROW_HEIGHT = 56
VIRTUAL_ROW_GAP = 10
VIRTUAL_OVERSCAN = 4


def ensure_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    default_settings = {
        "download_dir": str(DEFAULT_DOWNLOAD_DIR),
        "appearance_mode": "Dark",
        "hide_downloaded": True,
        "server_region": DEFAULT_REGION,
        "server_base_url": DEFAULT_BASE_URL,
    }
    if not APP_SETTINGS_FILE.exists():
        return default_settings
    try:
        loaded = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings
    return {**default_settings, **loaded}


def save_settings(settings: dict):
    APP_SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def current_palette() -> dict:
    mode = customtkinter.get_appearance_mode().lower()
    if mode == "light":
        return {
            "app_bg": "#f5f5f5",
            "header_bg": "#ffffff",
            "panel_bg": "#ffffff",
            "row_bg": "#ffffff",
            "text_muted": "#5f6673",
            "toolbar_btn": "#efefef",
            "toolbar_hover": "#e3e3e3",
            "dialog_bg": "#ffffff",
            "text_primary": "#111111",
            "accent": "#0d6efd",
            "accent_hover": "#0a58ca",
            "success": "#159a61",
            "success_hover": "#118252",
            "danger": "#bf3f46",
            "danger_hover": "#a23339",
        }
    return {
        "app_bg": "#080a0f",
        "header_bg": "#121722",
        "panel_bg": "#151c28",
        "row_bg": "#1a2230",
        "text_muted": "#d2dae8",
        "toolbar_btn": "#263243",
        "toolbar_hover": "#314156",
        "dialog_bg": "#151c28",
        "text_primary": "#f5f7fb",
        "accent": "#4d9fff",
        "accent_hover": "#7ab7ff",
        "success": "#22b573",
        "success_hover": "#39ca89",
        "danger": "#cf4d55",
        "danger_hover": "#e26169",
    }


def sanitize_title(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", title).strip()
    return cleaned or "sound"


def target_path_for(download_dir: Path, title: str) -> Path:
    return download_dir / f"{sanitize_title(title)}.mp3"


def format_bytes(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes:.1f} B"


def format_speed(num_bytes: float) -> str:
    return f"{format_bytes(num_bytes)}/s"


def themed_icon(path: str, size: tuple[int, int]) -> customtkinter.CTkImage:
    source = Image.open(path).convert("RGBA")
    light_icon = source.copy()
    dark_icon = source.copy()
    # New icons are black; invert them for dark mode to preserve contrast.
    dark_rgb = ImageOps.invert(dark_icon.convert("RGB"))
    dark_icon = Image.merge("RGBA", (*dark_rgb.split(), dark_icon.getchannel("A")))
    return customtkinter.CTkImage(light_image=light_icon, dark_image=dark_icon, size=size)


class VirtualizedList(customtkinter.CTkFrame):
    def __init__(self, master, row_height: int = VIRTUAL_ROW_HEIGHT, row_gap: int = VIRTUAL_ROW_GAP, **kwargs):
        super().__init__(master, **kwargs)
        self.row_height = row_height
        self.row_gap = row_gap
        self.total_row_height = row_height + row_gap
        self.items = []
        self.row_factory = None
        self.row_updater = None
        self.row_widgets = {}
        self.item_key = lambda item: id(item)
        self.empty_widget = None
        self.empty_window_id = None

        self.canvas = tkinter.Canvas(self, highlightthickness=0, borderwidth=0, bg=self._apply_appearance_mode(self._fg_color))
        self.scrollbar = customtkinter.CTkScrollbar(self, orientation="vertical", command=self._on_scrollbar)
        self.canvas.configure(yscrollcommand=self._on_canvas_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", lambda _event: self.refresh_visible_rows())
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def destroy(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except tkinter.TclError:
            pass
        return super().destroy()

    def _on_mousewheel(self, event):
        if not self.winfo_exists():
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        current = widget
        inside = False
        while current is not None:
            if current == self:
                inside = True
                break
            current = getattr(current, "master", None)
        if not inside:
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        self.refresh_visible_rows()

    def _on_scrollbar(self, *args):
        self.canvas.yview(*args)
        self.refresh_visible_rows()

    def _on_canvas_scroll(self, first, last):
        self.scrollbar.set(first, last)
        self.refresh_visible_rows()

    def clear(self):
        self.items = []
        for window_id, row in self.row_widgets.values():
            self.canvas.delete(window_id)
            row.destroy()
        self.row_widgets = {}
        if self.empty_window_id is not None:
            self.canvas.delete(self.empty_window_id)
            self.empty_window_id = None
        if self.empty_widget is not None:
            self.empty_widget.destroy()
            self.empty_widget = None
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

    def set_empty_widget(self, widget):
        self.clear()
        self.empty_widget = widget
        self.empty_window_id = self.canvas.create_window(0, 0, anchor="nw", window=widget)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), max(widget.winfo_reqheight() + 24, 100)))
        self.canvas.itemconfigure(self.empty_window_id, width=max(self.canvas.winfo_width() - 20, 100))

    def set_items(self, items, row_factory, row_updater=None, item_key=None):
        self.clear()
        self.items = list(items)
        self.row_factory = row_factory
        self.row_updater = row_updater
        if item_key is not None:
            self.item_key = item_key
        height = len(self.items) * self.total_row_height
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))
        self.canvas.yview_moveto(0)
        self.refresh_visible_rows()

    def refresh_visible_rows(self):
        if self.empty_window_id is not None:
            self.canvas.itemconfigure(self.empty_window_id, width=max(self.canvas.winfo_width() - 20, 100))
            self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), max(self.empty_widget.winfo_reqheight() + 24, 100)))
            return
        if not self.items or self.row_factory is None:
            return
        width = max(self.canvas.winfo_width() - 18, 100)
        top = self.canvas.canvasy(0)
        bottom = top + max(self.canvas.winfo_height(), 1)
        start = max(int(top // self.total_row_height) - VIRTUAL_OVERSCAN, 0)
        end = min(int(bottom // self.total_row_height) + VIRTUAL_OVERSCAN + 1, len(self.items))
        visible_keys = set()

        for index in range(start, end):
            item = self.items[index]
            key = self.item_key(item)
            y = index * self.total_row_height
            visible_keys.add(key)
            if key in self.row_widgets:
                window_id, row = self.row_widgets[key]
                self.canvas.coords(window_id, 8, y + 5)
                self.canvas.itemconfigure(window_id, width=width)
                if self.row_updater is not None:
                    self.row_updater(row, item, index)
            else:
                row = self.row_factory(self.canvas, item, index)
                window_id = self.canvas.create_window(8, y + 5, anchor="nw", width=width, height=self.row_height, window=row)
                self.row_widgets[key] = (window_id, row)

        for key in list(self.row_widgets.keys()):
            if key not in visible_keys:
                window_id, row = self.row_widgets.pop(key)
                self.canvas.delete(window_id)
                row.destroy()


class RowContextMenu:
    def __init__(self, master):
        self.menu = tkinter.Menu(master, tearoff=0)
        self.actions = []

    def set_actions(self, actions):
        self.actions = list(actions)
        self.menu.delete(0, "end")
        for label, command in self.actions:
            self.menu.add_command(label=label, command=command)

    def popup(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()


class DownloadProgressWindow(customtkinter.CTkToplevel):
    def __init__(self, master, items, on_complete, download_dir: Path, on_next_page=None):
        super().__init__(master)
        self.items = list(items)
        self.on_complete = on_complete
        self.download_dir = download_dir
        self.on_next_page = on_next_page
        self.cancel_requested = False
        self.cancel_current_requested = False
        self.closed = False
        self.completed_files = 0
        self.completed_bytes = 0
        self.total_expected_bytes = 0
        self.failed_items = []
        self.queue_running = False
        self.auto_next_page_var = tkinter.BooleanVar(value=False)
        palette = current_palette()
        self.title("Download Queue")
        self.geometry("720x420")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close_now)
        self.transient(master)
        self.grab_set()

        self.status_var = tkinter.StringVar(value="Preparing downloads...")
        self.file_var = tkinter.StringVar(value="Waiting for first file...")
        self.overall_var = tkinter.StringVar(value="0 / 0 files")
        self.speed_var = tkinter.StringVar(value="Speed: 0.0 B/s")
        self.bytes_var = tkinter.StringVar(value="Transferred: 0.0 B")

        container = customtkinter.CTkFrame(self, corner_radius=16, fg_color=palette["dialog_bg"])
        container.pack(fill="both", expand=True, padx=14, pady=14)

        title = customtkinter.CTkLabel(
            container,
            text="Batch Download Progress",
            font=customtkinter.CTkFont(family="Segoe UI", size=24, weight="bold"),
        )
        title.pack(anchor="w", padx=14, pady=(14, 6))

        status = customtkinter.CTkLabel(
            container,
            textvariable=self.status_var,
            font=customtkinter.CTkFont(family="Segoe UI", size=15),
        )
        status.pack(anchor="w", padx=14)

        current_file = customtkinter.CTkLabel(
            container,
            textvariable=self.file_var,
            wraplength=660,
            justify="left",
            font=customtkinter.CTkFont(family="Segoe UI", size=17, weight="bold"),
        )
        current_file.pack(anchor="w", padx=14, pady=(10, 6))

        self.file_progress = customtkinter.CTkProgressBar(container, height=16, progress_color="#18b36f")
        self.file_progress.pack(fill="x", padx=14)
        self.file_progress.set(0)

        file_meta = customtkinter.CTkFrame(container, fg_color="transparent")
        file_meta.pack(fill="x", padx=14, pady=(6, 10))

        speed = customtkinter.CTkLabel(file_meta, textvariable=self.speed_var, font=customtkinter.CTkFont(family="Segoe UI", size=14))
        speed.pack(side="left")

        bytes_label = customtkinter.CTkLabel(file_meta, textvariable=self.bytes_var, font=customtkinter.CTkFont(family="Segoe UI", size=14))
        bytes_label.pack(side="right")

        overall_title = customtkinter.CTkLabel(
            container,
            text="Queue Progress",
            font=customtkinter.CTkFont(family="Segoe UI", size=16, weight="bold"),
        )
        overall_title.pack(anchor="w", padx=14)

        self.overall_progress = customtkinter.CTkProgressBar(container, height=16, progress_color="#2d8cff")
        self.overall_progress.pack(fill="x", padx=14)
        self.overall_progress.set(0)

        overall_meta = customtkinter.CTkLabel(
            container,
            textvariable=self.overall_var,
            font=customtkinter.CTkFont(family="Segoe UI", size=14),
        )
        overall_meta.pack(anchor="w", padx=14, pady=(6, 12))

        self.log_box = customtkinter.CTkTextbox(container, height=120, corner_radius=12)
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log_box.insert("end", "Queue initialized.\n")
        self.log_box.configure(state="disabled")

        actions = customtkinter.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 14))

        self.next_page_controls = customtkinter.CTkFrame(actions, fg_color="transparent")

        self.auto_next_page_checkbox = customtkinter.CTkCheckBox(
            self.next_page_controls,
            text="Auto download next page",
            variable=self.auto_next_page_var,
            onvalue=True,
            offvalue=False,
        )
        self.auto_next_page_checkbox.pack(anchor="w")

        self.next_page_button = customtkinter.CTkButton(
            self.next_page_controls,
            text="Continue",
            command=self.handle_next_page,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            width=140,
        )
        self.next_page_button.pack(anchor="w", pady=(8, 0))

        self.retry_button = customtkinter.CTkButton(
            actions,
            text="Retry Failed",
            command=self.retry_failed,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            width=140,
        )

        self.cancel_current_button = customtkinter.CTkButton(
            actions,
            text="Cancel Current",
            command=self.request_cancel_current,
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
            width=140,
        )
        self.cancel_current_button.pack(side="right", padx=(0, 8))

        self.cancel_button = customtkinter.CTkButton(
            actions,
            text="Cancel Queue",
            command=self.request_cancel,
            fg_color=palette["danger"],
            hover_color=palette["danger_hover"],
            width=140,
        )
        self.cancel_button.pack(side="right")

        self.start_download_thread()

    def log(self, message: str):
        def _update():
            if self.closed or not self.winfo_exists():
                return
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.safe_after(_update)

    def safe_after(self, callback, *args):
        if self.closed:
            return
        try:
            if self.winfo_exists():
                self.after(0, callback, *args)
        except tkinter.TclError:
            return

    def request_cancel(self):
        self.cancel_requested = True
        if not self.closed:
            self.status_var.set("Cancel requested. Stopping queue...")
            self.cancel_current_button.configure(state="disabled", text="Stopping...")
            self.cancel_button.configure(state="disabled", text="Cancelling...")

    def request_cancel_current(self):
        if self.closed or not self.queue_running:
            return
        self.cancel_current_requested = True
        self.status_var.set("Cancel requested for current download...")
        self.cancel_current_button.configure(state="disabled", text="Cancelling...")

    def close_now(self):
        self.cancel_requested = True
        self.closed = True
        if self.on_complete:
            self.on_complete("Batch download dialog closed.")
        self.destroy()

    def handle_next_page(self):
        if self.on_next_page is None:
            return
        self.closed = True
        if self.on_complete:
            self.on_complete("Loading next page for download...")
        self.destroy()
        self.on_next_page(self.auto_next_page_var.get())

    def start_download_thread(self):
        self.queue_running = True
        threading.Thread(target=self.download_all, daemon=True).start()

    def retry_failed(self):
        if self.queue_running or not self.failed_items:
            return
        self.items = list(self.failed_items)
        self.failed_items = []
        self.cancel_requested = False
        self.cancel_current_requested = False
        self.completed_files = 0
        self.completed_bytes = 0
        self.total_expected_bytes = 0
        self.file_progress.set(0)
        self.overall_progress.set(0)
        self.speed_var.set("Speed: 0.0 B/s")
        self.bytes_var.set("Transferred: 0.0 B")
        self.overall_var.set(f"0 / {len(self.items)} files")
        self.file_var.set("Retrying failed downloads...")
        self.status_var.set("Retrying failed downloads...")
        self.retry_button.pack_forget()
        self.next_page_controls.pack_forget()
        self.cancel_current_button.configure(state="normal", text="Cancel Current", command=self.request_cancel_current)
        self.cancel_button.configure(state="normal", text="Cancel Queue", command=self.request_cancel)
        self.log(f"Retrying {len(self.items)} failed downloads.")
        self.start_download_thread()

    def update_progress(self, file_name, file_progress, file_bytes, speed, overall_fraction):
        self.file_var.set(f"Current file: {file_name}")
        self.file_progress.set(file_progress)
        self.overall_progress.set(overall_fraction)
        self.speed_var.set(f"Speed: {format_speed(speed)}")
        self.bytes_var.set(f"Transferred: {format_bytes(file_bytes)}")
        self.overall_var.set(
            f"{self.completed_files} / {len(self.items)} files complete | "
            f"{format_bytes(self.completed_bytes + file_bytes)} downloaded"
        )

    def finish_queue(self, message: str):
        if self.closed or not self.winfo_exists():
            return
        self.queue_running = False
        self.status_var.set(message)
        self.cancel_current_button.configure(state="disabled", text="Cancel Current")
        self.cancel_button.configure(text="Close", state="normal", command=self.close_now)
        self.retry_button.pack_forget()
        self.next_page_controls.pack_forget()
        if self.failed_items:
            self.retry_button.pack(side="left", padx=(0, 8))
        if self.on_next_page is not None and not self.cancel_requested and not self.failed_items:
            self.next_page_controls.pack(side="left")
        if self.on_complete:
            self.on_complete(message)

    def download_single(self, item):
        target_path = target_path_for(self.download_dir, item["title"])
        if target_path.exists():
            self.completed_files += 1
            self.log(f"Skipped existing file {target_path.name}")
            self.safe_after(
                self.update_progress,
                item["title"],
                1,
                0,
                0,
                self.completed_files / max(len(self.items), 1),
            )
            return
        downloaded = 0
        started = perf_counter()
        with requests.get(item["url"], stream=True, timeout=30) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", "0") or 0)
            if total_size:
                self.total_expected_bytes += total_size
            try:
                with open(target_path, "wb") as audio_file:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if self.cancel_requested:
                            raise RuntimeError("Download cancelled by user.")
                        if self.cancel_current_requested:
                            raise RuntimeError("Current download cancelled by user.")
                        if not chunk:
                            continue
                        audio_file.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(perf_counter() - started, 0.001)
                        speed = downloaded / elapsed
                        file_progress = (downloaded / total_size) if total_size else 0
                        overall_fraction = (self.completed_files + file_progress) / max(len(self.items), 1)
                        self.safe_after(
                            self.update_progress,
                            item["title"],
                            min(file_progress, 1),
                            downloaded,
                            speed,
                            min(overall_fraction, 1),
                        )
            except Exception:
                if target_path.exists() and downloaded > 0:
                    try:
                        target_path.unlink()
                    except OSError:
                        pass
                raise
        self.completed_files += 1
        self.completed_bytes += downloaded
        self.safe_after(
            self.update_progress,
            item["title"],
            1,
            downloaded,
            0,
            self.completed_files / max(len(self.items), 1),
        )
        self.log(f"Saved {target_path.name}")

    def download_all(self):
        try:
            total = len(self.items)
            self.safe_after(self.overall_var.set, f"0 / {total} files")
            for item in self.items:
                if self.cancel_requested:
                    break
                self.safe_after(self.status_var.set, "Downloading files from the current list...")
                self.cancel_current_requested = False
                self.safe_after(
                    lambda: self.cancel_current_button.configure(
                        state="normal",
                        text="Cancel Current",
                        command=self.request_cancel_current,
                    )
                )
                try:
                    self.download_single(item)
                except RuntimeError as exc:
                    if str(exc) == "Current download cancelled by user.":
                        self.failed_items.append(item)
                        self.log(f"Cancelled current download: {item['title']}")
                        self.safe_after(self.file_var.set, f"Skipped current file: {item['title']}")
                        self.safe_after(self.file_progress.set, 0)
                        self.safe_after(self.speed_var.set, "Speed: 0.0 B/s")
                        continue
                    raise
                except Exception as exc:
                    self.failed_items.append(item)
                    self.log(f"Failed {item['title']}: {exc}")
            if self.cancel_requested:
                self.log("Queue cancelled.")
                self.safe_after(self.finish_queue, "Download queue cancelled.")
            elif self.failed_items:
                self.log("Queue finished with failures.")
                self.safe_after(
                    self.finish_queue,
                    f"Completed with {len(self.failed_items)} failed download(s).",
                )
            else:
                self.log("Queue completed successfully.")
                self.safe_after(self.finish_queue, "All files from the current page were downloaded.")
        except Exception as exc:
            self.log(f"Error: {exc}")
            self.safe_after(self.finish_queue, f"Download queue stopped: {exc}")


class SoundRow(customtkinter.CTkFrame):
    def __init__(self, master, item, play_command, download_command, icon_image, play_icon, palette, context_menu=None):
        super().__init__(master, fg_color=palette["row_bg"], corner_radius=12)
        self.palette = palette
        self.context_menu = context_menu
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=0)

        self.title_label = customtkinter.CTkLabel(
            self,
            text=item["title"],
            anchor="w",
            justify="left",
            wraplength=650,
            font=customtkinter.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=palette["text_primary"],
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=10)

        play_button = customtkinter.CTkButton(
            self,
            text="Play",
            width=90,
            image=play_icon,
            compound="left",
            command=play_command,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            text_color=palette["text_primary"],
        )
        play_button.grid(row=0, column=1, padx=4, pady=8)

        self.download_button = customtkinter.CTkButton(
            self,
            text="",
            width=42,
            image=icon_image,
            command=download_command,
            fg_color=palette["success"],
            hover_color=palette["success_hover"],
        )
        self.download_button.grid(row=0, column=2, padx=(4, 10), pady=8)
        self.bind_context_menu(self)
        self.bind_context_menu(self.title_label)
        self.bind_context_menu(play_button)
        self.bind_context_menu(self.download_button)

    def bind_context_menu(self, widget):
        if self.context_menu is None:
            return
        widget.bind("<Button-3>", self.context_menu.popup, add="+")

    def set_downloading(self, is_downloading: bool):
        if is_downloading:
            self.download_button.configure(
                state="disabled",
                fg_color=self.palette["accent"],
                hover_color=self.palette["accent"],
            )
        else:
            self.download_button.configure(
                state="normal",
                fg_color=self.palette["success"],
                hover_color=self.palette["success_hover"],
            )

    def set_downloaded(self, is_downloaded: bool):
        if is_downloaded:
            self.title_label.configure(text_color=self.palette["success"])
            self.download_button.configure(
                state="disabled",
                fg_color=self.palette["success"],
                hover_color=self.palette["success"],
            )
        else:
            self.title_label.configure(text_color=self.palette["text_primary"])
            self.download_button.configure(
                state="normal",
                fg_color=self.palette["success"],
                hover_color=self.palette["success_hover"],
            )


class InventoryRow(customtkinter.CTkFrame):
    def __init__(self, master, app_controller, file_path: Path, play_command, open_command, rename_command, delete_command, context_menu, palette):
        super().__init__(master, fg_color=palette["row_bg"], corner_radius=12)
        self.app_controller = app_controller
        self.palette = palette
        self.context_menu = context_menu
        self.grid_columnconfigure(0, weight=1)

        self.file_label = customtkinter.CTkLabel(
            self,
            text=file_path.stem,
            anchor="w",
            justify="left",
            wraplength=500,
            font=customtkinter.CTkFont(family="Segoe UI", size=16, weight="bold"),
        )
        self.file_label.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=10)

        self.play_button = customtkinter.CTkButton(
            self,
            text="Play",
            width=90,
            image=self.app_controller.play_icon,
            compound="left",
            command=play_command,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            text_color=palette["text_primary"],
        )
        self.play_button.grid(row=0, column=1, padx=4, pady=8)

        self.open_button = customtkinter.CTkButton(
            self,
            text="Open",
            width=90,
            command=open_command,
            image=self.app_controller.folder_open_icon,
            compound="left",
            fg_color=palette["success"],
            hover_color=palette["success_hover"],
        )
        self.open_button.grid(row=0, column=2, padx=4, pady=8)

        self.rename_button = customtkinter.CTkButton(
            self,
            text="Rename",
            width=90,
            command=rename_command,
            image=self.app_controller.rename_icon,
            compound="left",
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
            text_color=palette["text_primary"],
        )
        self.rename_button.grid(row=0, column=3, padx=4, pady=8)

        self.delete_button = customtkinter.CTkButton(
            self,
            text="Delete",
            width=90,
            command=delete_command,
            image=self.app_controller.delete_icon,
            compound="left",
            fg_color=palette["danger"],
            hover_color=palette["danger_hover"],
        )
        self.delete_button.grid(row=0, column=4, padx=(4, 10), pady=8)

        for widget in (self, self.file_label, self.play_button, self.open_button, self.rename_button, self.delete_button):
            widget.bind("<Button-3>", self.context_menu.popup, add="+")

class SettingsWindow(customtkinter.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.app)
        self.app_controller = app
        palette = current_palette()
        self.title("Settings")
        self.geometry("620x320")
        self.resizable(False, False)
        self.transient(app.app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.download_dir_var = tkinter.StringVar(value=str(app.download_dir.resolve()))
        self.appearance_var = tkinter.StringVar(value=app.settings.get("appearance_mode", "Dark"))
        self.hide_downloaded_var = tkinter.BooleanVar(value=app.settings.get("hide_downloaded", True))
        self.server_choice_var = tkinter.StringVar(value=self.get_server_choice())
        self.server_custom_region_var = tkinter.StringVar(value=app.server_region if app.server_region not in {"us", "in"} else "")
        self.server_base_url_var = tkinter.StringVar(value=app.server_base_url)

        container = customtkinter.CTkFrame(self, corner_radius=16, fg_color=palette["dialog_bg"])
        container.pack(fill="both", expand=True, padx=14, pady=14)

        title = customtkinter.CTkLabel(
            container,
            text="Settings",
            font=customtkinter.CTkFont(family="Segoe UI", size=24, weight="bold"),
        )
        title.pack(anchor="w", padx=14, pady=(14, 6))

        description = customtkinter.CTkLabel(
            container,
            text="Choose where downloads are stored and which theme the app should use.",
            text_color=palette["text_muted"],
            font=customtkinter.CTkFont(family="Segoe UI", size=14),
        )
        description.pack(anchor="w", padx=14, pady=(0, 12))

        folder_row = customtkinter.CTkFrame(container, fg_color="transparent")
        folder_row.pack(fill="x", padx=14, pady=(0, 10))

        folder_label = customtkinter.CTkLabel(folder_row, text="Downloads Folder", width=130, anchor="w")
        folder_label.pack(side="left")

        folder_entry = customtkinter.CTkEntry(folder_row, textvariable=self.download_dir_var, width=340, height=36)
        folder_entry.pack(side="left", padx=(0, 8))

        browse_button = customtkinter.CTkButton(
            folder_row,
            text="Browse",
            width=90,
            height=36,
            command=self.browse_folder,
            image=self.app_controller.folder_open_icon,
            compound="left",
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            text_color=palette["text_primary"],
        )
        browse_button.pack(side="left")

        appearance_row = customtkinter.CTkFrame(container, fg_color="transparent")
        appearance_row.pack(fill="x", padx=14, pady=(0, 14))

        appearance_label = customtkinter.CTkLabel(appearance_row, text="Theme", width=130, anchor="w")
        appearance_label.pack(side="left")

        appearance_menu = customtkinter.CTkOptionMenu(
            appearance_row,
            values=["Dark", "Light", "System"],
            variable=self.appearance_var,
            width=180,
        )
        appearance_menu.pack(side="left")

        filter_row = customtkinter.CTkFrame(container, fg_color="transparent")
        filter_row.pack(fill="x", padx=14, pady=(0, 14))

        filter_label = customtkinter.CTkLabel(filter_row, text="Hide Downloaded", width=130, anchor="w")
        filter_label.pack(side="left")

        filter_switch = customtkinter.CTkSwitch(
            filter_row,
            text="On",
            variable=self.hide_downloaded_var,
            onvalue=True,
            offvalue=False,
        )
        filter_switch.pack(side="left")

        server_row = customtkinter.CTkFrame(container, fg_color="transparent")
        server_row.pack(fill="x", padx=14, pady=(0, 10))

        server_label = customtkinter.CTkLabel(server_row, text="Server", width=130, anchor="w")
        server_label.pack(side="left")

        server_menu = customtkinter.CTkOptionMenu(
            server_row,
            values=["US", "IN", "Custom"],
            variable=self.server_choice_var,
            width=180,
            command=lambda _value: self.update_server_fields(),
        )
        server_menu.pack(side="left")

        custom_region_row = customtkinter.CTkFrame(container, fg_color="transparent")
        custom_region_row.pack(fill="x", padx=14, pady=(0, 10))

        self.custom_region_label = customtkinter.CTkLabel(custom_region_row, text="Custom Region", width=130, anchor="w")
        self.custom_region_label.pack(side="left")

        self.custom_region_entry = customtkinter.CTkEntry(
            custom_region_row,
            textvariable=self.server_custom_region_var,
            width=180,
            height=36,
            placeholder_text="us, in, etc.",
        )
        self.custom_region_entry.pack(side="left")

        base_url_row = customtkinter.CTkFrame(container, fg_color="transparent")
        base_url_row.pack(fill="x", padx=14, pady=(0, 14))

        base_url_label = customtkinter.CTkLabel(base_url_row, text="Base URL", width=130, anchor="w")
        base_url_label.pack(side="left")

        base_url_entry = customtkinter.CTkEntry(
            base_url_row,
            textvariable=self.server_base_url_var,
            width=340,
            height=36,
            placeholder_text="https://www.myinstants.com",
        )
        base_url_entry.pack(side="left")

        buttons = customtkinter.CTkFrame(container, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(6, 14))

        save_button = customtkinter.CTkButton(
            buttons,
            text="Save",
            width=100,
            command=self.save,
            fg_color=palette["success"],
            hover_color=palette["success_hover"],
        )
        save_button.pack(side="right")

        cancel_button = customtkinter.CTkButton(
            buttons,
            text="Cancel",
            width=100,
            command=self.close,
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
        )
        cancel_button.pack(side="right", padx=(0, 8))
        self.update_server_fields()

    def get_server_choice(self) -> str:
        region = self.app_controller.server_region.lower()
        if region == "us":
            return "US"
        if region == "in":
            return "IN"
        return "Custom"

    def update_server_fields(self):
        is_custom = self.server_choice_var.get() == "Custom"
        self.custom_region_entry.configure(state="normal" if is_custom else "disabled")
        self.custom_region_label.configure(text_color=current_palette()["text_primary"] if is_custom else current_palette()["text_muted"])

    def browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.download_dir_var.get() or os.getcwd())
        if selected:
            self.download_dir_var.set(selected)

    def save(self):
        selected_dir = Path(self.download_dir_var.get()).expanduser()
        server_choice = self.server_choice_var.get()
        custom_region = self.server_custom_region_var.get().strip()
        if server_choice == "US":
            region = "us"
        elif server_choice == "IN":
            region = "in"
        else:
            region = custom_region
        try:
            normalized_region = normalize_region(region)
            normalized_base_url = normalize_base_url(self.server_base_url_var.get())
        except Exception as exc:
            messagebox.showerror("Settings Error", f"Invalid server configuration: {exc}", parent=self)
            return
        if server_choice == "Custom" and not custom_region:
            messagebox.showerror("Settings Error", "Enter a custom region code before saving.", parent=self)
            return
        ensure_directory(selected_dir)
        self.app_controller.settings["download_dir"] = str(selected_dir)
        self.app_controller.settings["appearance_mode"] = self.appearance_var.get()
        self.app_controller.settings["hide_downloaded"] = self.hide_downloaded_var.get()
        self.app_controller.settings["server_region"] = normalized_region
        self.app_controller.settings["server_base_url"] = normalized_base_url
        save_settings(self.app_controller.settings)
        self.app_controller.download_dir = selected_dir
        self.app_controller.hide_downloaded = self.hide_downloaded_var.get()
        self.app_controller.server_region = normalized_region
        self.app_controller.server_base_url = normalized_base_url
        self.app_controller.prefetched_pages.clear()
        self.app_controller.page_prefetching.clear()
        self.app_controller.apply_appearance_mode(self.appearance_var.get(), persist=False)
        self.app_controller.set_status(f"Downloads folder set to {selected_dir} | Server {normalized_region.upper()}")
        self.close()

    def close(self):
        self.app_controller.settings_window = None
        self.destroy()


class InventoryWindow(customtkinter.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.app)
        self.app_controller = app
        self.refresh_token = 0
        self.inventory_files = []
        palette = current_palette()
        self.title("Inventory")
        self.geometry("760x520")
        self.minsize(640, 420)
        self.transient(app.app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.close)

        container = customtkinter.CTkFrame(self, corner_radius=16, fg_color=palette["dialog_bg"])
        container.pack(fill="both", expand=True, padx=14, pady=14)

        title = customtkinter.CTkLabel(
            container,
            text="Downloaded Sound Effects",
            font=customtkinter.CTkFont(family="Segoe UI", size=24, weight="bold"),
        )
        title.pack(anchor="w", padx=14, pady=(14, 4))

        self.summary_var = tkinter.StringVar(value="")
        summary = customtkinter.CTkLabel(
            container,
            textvariable=self.summary_var,
            text_color=palette["text_muted"],
            font=customtkinter.CTkFont(family="Segoe UI", size=14),
        )
        summary.pack(anchor="w", padx=14, pady=(0, 10))

        actions = customtkinter.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 10))

        refresh_button = customtkinter.CTkButton(
            actions,
            text="Refresh",
            width=110,
            command=self.refresh_inventory,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
        )
        refresh_button.pack(side="left")

        open_folder_button = customtkinter.CTkButton(
            actions,
            text="Open Downloads",
            width=140,
            command=app.open_download_folder,
            image=self.app_controller.folder_open_icon,
            compound="left",
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
            text_color=palette["text_primary"],
        )
        open_folder_button.pack(side="left", padx=(8, 0))

        self.list_frame = VirtualizedList(
            container,
            fg_color=palette["panel_bg"],
            corner_radius=14,
        )
        self.list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.refresh_inventory()

    def _safe_after(self, callback, *args):
        try:
            if self.winfo_exists():
                self.after(0, callback, *args)
        except tkinter.TclError:
            return

    def _clear_rows(self):
        self.list_frame.clear()

    def _show_loading_state(self, message: str):
        self._clear_rows()
        self.summary_var.set(message)
        loading = customtkinter.CTkLabel(
            self.list_frame.canvas,
            text="Loading inventory...",
            font=customtkinter.CTkFont(family="Segoe UI", size=18),
        )
        self.list_frame.set_empty_widget(loading)

    def _build_empty_inventory(self):
        palette = current_palette()
        empty = customtkinter.CTkFrame(self.list_frame.canvas, fg_color="transparent")
        empty_icon = customtkinter.CTkLabel(empty, text="", image=self.app_controller.inventory_icon)
        empty_icon.pack(anchor="w", pady=(0, 10))
        empty_text = customtkinter.CTkLabel(
            empty,
            text="No downloaded sound effects found.",
            font=customtkinter.CTkFont(family="Segoe UI", size=18),
        )
        empty_text.pack(anchor="w")
        action = customtkinter.CTkButton(
            empty,
            text="Open Downloads Folder",
            command=self.app_controller.open_download_folder,
            image=self.app_controller.folder_open_icon,
            compound="left",
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
        )
        action.pack(anchor="w", pady=(12, 0))
        return empty

    def _show_inventory_context_menu(self, event, file_path: Path):
        menu = RowContextMenu(self)
        menu.set_actions([
            ("Play", lambda current=file_path: self.play_inventory_file(current)),
            ("Reveal", lambda current=file_path: os.startfile(str(current))),
            ("Rename", lambda current=file_path: self.rename_item(current)),
            ("Delete", lambda current=file_path: self.delete_item(current)),
            ("Copy Path", lambda current=file_path: self.copy_path(current)),
        ])
        menu.popup(event)

    def play_inventory_file(self, file_path: Path):
        self.app_controller.set_status(f"Playing: {file_path.stem}")
        threading.Thread(target=playsound, args=(str(file_path),), daemon=True).start()

    def copy_path(self, file_path: Path):
        self.clipboard_clear()
        self.clipboard_append(str(file_path.resolve()))
        self.app_controller.set_status(f"Copied path: {file_path.name}")

    def _create_inventory_row(self, _master, file_path: Path, _index: int):
        palette = current_palette()
        context_menu = RowContextMenu(self)
        context_menu.set_actions([
            ("Play", lambda current=file_path: self.play_inventory_file(current)),
            ("Reveal", lambda current=file_path: os.startfile(str(current))),
            ("Rename", lambda current=file_path: self.rename_item(current)),
            ("Delete", lambda current=file_path: self.delete_item(current)),
            ("Copy Path", lambda current=file_path: self.copy_path(current)),
        ])
        return InventoryRow(
            self.list_frame.canvas,
            self.app_controller,
            file_path,
            play_command=lambda current=file_path: self.play_inventory_file(current),
            open_command=lambda current=file_path: os.startfile(str(current)),
            rename_command=lambda current=file_path: self.rename_item(current),
            delete_command=lambda current=file_path: self.delete_item(current),
            context_menu=context_menu,
            palette=palette,
        )

    def _finish_inventory_refresh(self, files, token: int):
        if token != self.refresh_token or not self.winfo_exists():
            return
        self._clear_rows()
        self.inventory_files = list(files)
        self.summary_var.set(f"{len(files)} downloaded sound effect(s)")

        if not files:
            self.list_frame.set_empty_widget(self._build_empty_inventory())
            return

        self.list_frame.set_items(files, self._create_inventory_row, item_key=lambda path: str(path))

    def refresh_inventory(self):
        self.refresh_token += 1
        token = self.refresh_token
        self._show_loading_state("Loading inventory...")

        def _worker():
            try:
                files = sorted(self.app_controller.download_dir.glob("*.mp3"), key=lambda path: path.name.lower())
            except Exception as exc:
                self._safe_after(self.summary_var.set, f"Unable to load inventory: {exc}")
                return
            self._safe_after(self._finish_inventory_refresh, files, token)

        threading.Thread(target=_worker, daemon=True).start()

    def rename_item(self, file_path: Path):
        new_name = simpledialog.askstring(
            "Rename Sound",
            "Enter a new name for this sound:",
            initialvalue=file_path.stem,
            parent=self,
        )
        if new_name is None:
            return
        cleaned_name = sanitize_title(new_name).strip()
        if not cleaned_name:
            messagebox.showerror("Rename Failed", "Please enter a valid file name.", parent=self)
            return
        target_path = file_path.with_name(f"{cleaned_name}.mp3")
        if target_path == file_path:
            return
        if target_path.exists():
            messagebox.showerror("Rename Failed", "A sound with that name already exists.", parent=self)
            return
        try:
            file_path.rename(target_path)
        except OSError as exc:
            messagebox.showerror("Rename Failed", str(exc), parent=self)
            return
        self.app_controller.set_status(f"Renamed {file_path.name} to {target_path.name}")
        self.app_controller.render_items(self.app_controller.current_items, self.app_controller.status_var.get())
        self.refresh_inventory()

    def delete_item(self, file_path: Path):
        confirmed = messagebox.askyesno(
            "Delete Sound",
            f"Delete '{file_path.name}' from downloads?",
            parent=self,
        )
        if not confirmed:
            return
        try:
            file_path.unlink()
        except OSError as exc:
            messagebox.showerror("Delete Failed", str(exc), parent=self)
            return
        self.app_controller.set_status(f"Deleted {file_path.name}")
        self.app_controller.render_items(self.app_controller.current_items, self.app_controller.status_var.get())
        self.refresh_inventory()

    def close(self):
        self.app_controller.inventory_window = None
        self.destroy()


class MyInstantsApp:
    def __init__(self):
        self.settings = load_settings()
        ensure_directory(Path(self.settings["download_dir"]).expanduser())
        self.download_dir = Path(self.settings["download_dir"]).expanduser()
        self.page_no = 1
        self.current_items = []
        self.row_widgets = {}
        self.active_downloads = set()
        self.hide_downloaded = self.settings.get("hide_downloaded", True)
        self.server_region = normalize_region(self.settings.get("server_region", DEFAULT_REGION))
        self.server_base_url = normalize_base_url(self.settings.get("server_base_url", DEFAULT_BASE_URL))
        self.current_mode = "page"
        self.last_search_query = ""
        self.batch_window = None
        self.settings_window = None
        self.inventory_window = None
        self.auto_download_page_on_load = None
        self.prefetched_pages = {}
        self.page_fetch_tokens = {}
        self.page_prefetching = set()
        self.visible_items = []

        customtkinter.set_appearance_mode(self.settings.get("appearance_mode", "Dark"))

        self.app = customtkinter.CTk()
        self.app.geometry("1320x860")
        self.app.minsize(1100, 760)
        self.app.title(f"{APP_TITLE} | {self.status_var.get() if hasattr(self, 'status_var') else 'Starting'}")
        self.app.winfo_toplevel().iconbitmap("main.ico")
        self.app.configure(fg_color=current_palette()["app_bg"])

        self.download_icon = themed_icon("download.png", (16, 16))
        self.hero_icon = themed_icon("flush.png", (56, 56))
        self.folder_icon = themed_icon("archive.png", (16, 16))
        self.left_icon = themed_icon("arrow-left.png", (14, 14))
        self.right_icon = themed_icon("arrow-right.png", (14, 14))
        self.search_icon = themed_icon("search.png", (14, 14))
        self.search_empty_icon = themed_icon("search.png", (42, 42))
        self.play_icon = themed_icon("play-fill.png", (14, 14))
        self.settings_icon = themed_icon("gear-fill.png", (14, 14))
        self.home_icon = themed_icon("house.png", (14, 14))
        self.inventory_icon = themed_icon("box2-fill.png", (16, 16))
        self.rename_icon = themed_icon("cursor-text.png", (16, 16))
        self.folder_open_icon = themed_icon("folder2-open.png", (16, 16))
        self.delete_icon = themed_icon("trash3.png", (16, 16))

        self.status_var = tkinter.StringVar(value="Loading page 1...")
        self.subtitle_var = tkinter.StringVar(value="Quickly download sounds from MyInstants!")
        self.page_var = tkinter.StringVar(value="Page 1")
        self.result_var = tkinter.StringVar(value="Loading...")
        self.list_title_var = tkinter.StringVar(value="Page 1")

        self.build_menu()
        self.build_layout()
        self.load_page(1)

    def build_menu(self):
        menubar = tkinter.Menu(self.app)

        file_menu = tkinter.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Download All On Current View", command=self.download_all_current)
        file_menu.add_command(label="Inventory", command=self.open_inventory)
        file_menu.add_command(label="Open Downloads Folder", command=self.open_download_folder)
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.app.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        navigate_menu = tkinter.Menu(menubar, tearoff=0)
        navigate_menu.add_command(label="Back To Trending", command=lambda: self.load_page(1))
        navigate_menu.add_separator()
        navigate_menu.add_command(label="Previous Page", command=self.prev_page)
        navigate_menu.add_command(label="Next Page", command=self.next_page)
        navigate_menu.add_separator()
        navigate_menu.add_command(label="Reload Current View", command=self.reload_current_view)
        menubar.add_cascade(label="Navigate", menu=navigate_menu)

        appearance_menu = tkinter.Menu(menubar, tearoff=0)
        appearance_menu.add_command(label="System Theme", command=lambda: self.apply_appearance_mode("System"))
        appearance_menu.add_command(label="Dark Theme", command=lambda: self.apply_appearance_mode("Dark"))
        appearance_menu.add_command(label="Light Theme", command=lambda: self.apply_appearance_mode("Light"))
        menubar.add_cascade(label="View", menu=appearance_menu)

        help_menu = tkinter.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="About",
            command=lambda: messagebox.showinfo(
                "About",
                "MyInstants Downloader and Player\nImproved list view, menu bar, and batch downloads.\nImproved version by RiffPointer.",
            ),
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.app.configure(menu=menubar)

    def build_layout(self):
        palette = current_palette()

        outer = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color=palette["app_bg"])
        outer.pack(fill="both", expand=True)

        content = customtkinter.CTkFrame(outer, corner_radius=0, fg_color=palette["app_bg"])
        content.pack(fill="both", expand=True, padx=16, pady=16)

        toolbar = customtkinter.CTkFrame(content, corner_radius=14, fg_color=palette["panel_bg"])
        toolbar.pack(fill="x", pady=(0, 12))

        folder_button = customtkinter.CTkButton(
            toolbar,
            text="Open Downloads",
            width=140,
            command=self.open_download_folder,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            image=self.folder_icon,
            compound="left",
            text_color=palette["text_primary"],
        )
        folder_button.pack(side="left", padx=(14, 6), pady=8)

        download_button = customtkinter.CTkButton(
            toolbar,
            text="Download All",
            width=130,
            command=self.download_all_current,
            fg_color=palette["success"],
            hover_color=palette["success_hover"],
            image=self.download_icon,
            compound="left",
        )
        download_button.pack(side="left", padx=(0, 10), pady=8)

        inventory_button = customtkinter.CTkButton(
            toolbar,
            text="Inventory",
            width=120,
            command=self.open_inventory,
            image=self.inventory_icon,
            compound="left",
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            text_color=palette["text_primary"],
        )
        inventory_button.pack(side="left", padx=(0, 6), pady=8)

        right_controls = customtkinter.CTkFrame(toolbar, fg_color="transparent")
        right_controls.pack(side="right", padx=8, pady=6)

        self.search_entry = customtkinter.CTkEntry(
            right_controls,
            width=250,
            height=36,
            placeholder_text="Search sounds",
            corner_radius=8,
            border_width=1,
        )
        self.search_entry.pack(side="left", padx=(0, 6))
        self.search_entry.bind("<Return>", lambda _event: self.search())

        search_button = customtkinter.CTkButton(
            right_controls,
            text="Search",
            image=self.search_icon,
            compound="left",
            width=110,
            height=36,
            command=self.search,
            fg_color=palette["accent"],
            hover_color=palette["accent_hover"],
            text_color=palette["text_primary"],
        )
        search_button.pack(side="left")

        list_panel = customtkinter.CTkFrame(content, corner_radius=16, fg_color=palette["panel_bg"])
        list_panel.pack(fill="both", expand=True)

        list_header = customtkinter.CTkFrame(list_panel, fg_color="transparent")
        list_header.pack(fill="x", padx=14, pady=(12, 6))

        list_title = customtkinter.CTkLabel(
            list_header,
            textvariable=self.list_title_var,
            font=customtkinter.CTkFont(family="Segoe UI", size=20, weight="bold"),
        )
        list_title.pack(side="left")

        list_right = customtkinter.CTkFrame(list_header, fg_color="transparent")
        list_right.pack(side="right")

        list_hint = customtkinter.CTkLabel(
            list_right,
            textvariable=self.result_var,
            font=customtkinter.CTkFont(family="Segoe UI", size=14),
            text_color=palette["text_muted"],
        )
        list_hint.pack(side="left", padx=(0, 12))

        prev_button = customtkinter.CTkButton(
            list_right,
            text="Prev",
            image=self.left_icon,
            compound="left",
            width=90,
            command=self.prev_page,
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
            text_color=palette["text_primary"],
        )
        prev_button.pack(side="left", padx=(0, 6), pady=2)

        next_button = customtkinter.CTkButton(
            list_right,
            text="Next",
            image=self.right_icon,
            compound="right",
            width=90,
            command=self.next_page,
            fg_color=palette["toolbar_btn"],
            hover_color=palette["toolbar_hover"],
            text_color=palette["text_primary"],
        )
        next_button.pack(side="left", pady=2)

        self.list_frame = VirtualizedList(
            list_panel,
            fg_color=palette["panel_bg"],
            corner_radius=14,
        )
        self.list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def set_status(self, message: str):
        self.status_var.set(message)
        self.app.title(f"{APP_TITLE} | {message}")

    def set_loading_state(self, status_message: str, results_message: str = "Loading..."):
        self.set_status(status_message)
        self.result_var.set(results_message)

    def set_row_downloading(self, item, is_downloading: bool):
        key = item["url"]
        row = self.row_widgets.get(key)
        if row is not None and row.winfo_exists():
            row.set_downloading(is_downloading)
        if is_downloading:
            self.active_downloads.add(key)
        else:
            self.active_downloads.discard(key)
            if row is not None and row.winfo_exists():
                row.set_downloaded(target_path_for(self.download_dir, item["title"]).exists())

    def play_sound(self, item):
        self.set_status(f"Playing: {item['title']}")
        threading.Thread(target=playsound, args=(item["url"],), daemon=True).start()

    def download_item(self, item):
        key = item["url"]
        if key in self.active_downloads:
            return

        def _worker():
            try:
                target_path = target_path_for(self.download_dir, item["title"])
                if target_path.exists():
                    self.app.after(0, self.set_status, f"Skipped existing file {target_path.name}")
                    return
                self.app.after(0, self.set_status, f"Downloading {target_path.name}...")
                with requests.get(item["url"], stream=True, timeout=30) as response:
                    response.raise_for_status()
                    with open(target_path, "wb") as audio_file:
                        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                            if chunk:
                                audio_file.write(chunk)
                self.app.after(0, self.set_status, f"Downloaded {target_path.name}")
            except Exception as exc:
                self.app.after(0, self.set_status, f"Download failed: {exc}")
            finally:
                self.app.after(0, self.set_row_downloading, item, False)

        self.set_row_downloading(item, True)
        threading.Thread(target=_worker, daemon=True).start()

    def clear_list(self):
        self.row_widgets = {}
        self.list_frame.clear()

    def copy_path_to_clipboard(self, file_path: Path):
        self.app.clipboard_clear()
        self.app.clipboard_append(str(file_path.resolve()))
        self.set_status(f"Copied path: {file_path.name}")

    def rename_downloaded_item(self, file_path: Path):
        if self.inventory_window is not None and self.inventory_window.winfo_exists():
            self.inventory_window.rename_item(file_path)
            return
        new_name = simpledialog.askstring(
            "Rename Sound",
            "Enter a new name for this sound:",
            initialvalue=file_path.stem,
            parent=self.app,
        )
        if new_name is None:
            return
        cleaned_name = sanitize_title(new_name).strip()
        if not cleaned_name:
            messagebox.showerror("Rename Failed", "Please enter a valid file name.", parent=self.app)
            return
        target_path = file_path.with_name(f"{cleaned_name}.mp3")
        if target_path == file_path:
            return
        if target_path.exists():
            messagebox.showerror("Rename Failed", "A sound with that name already exists.", parent=self.app)
            return
        try:
            file_path.rename(target_path)
        except OSError as exc:
            messagebox.showerror("Rename Failed", str(exc), parent=self.app)
            return
        self.set_status(f"Renamed {file_path.name} to {target_path.name}")
        self.render_items(self.current_items, self.status_var.get())

    def delete_downloaded_item(self, file_path: Path):
        if self.inventory_window is not None and self.inventory_window.winfo_exists():
            self.inventory_window.delete_item(file_path)
            return
        confirmed = messagebox.askyesno("Delete Sound", f"Delete '{file_path.name}' from downloads?", parent=self.app)
        if not confirmed:
            return
        try:
            file_path.unlink()
        except OSError as exc:
            messagebox.showerror("Delete Failed", str(exc), parent=self.app)
            return
        self.set_status(f"Deleted {file_path.name}")
        self.render_items(self.current_items, self.status_var.get())

    def _build_main_empty_state(self, items):
        palette = current_palette()
        empty = customtkinter.CTkFrame(self.list_frame.canvas, fg_color="transparent")
        empty_icon = customtkinter.CTkLabel(empty, text="", image=self.search_empty_icon)
        empty_icon.pack(anchor="w", pady=(0, 10))
        if self.current_mode == "search" and self.last_search_query:
            empty_text = customtkinter.CTkLabel(empty, text="No sounds found for this search.", font=customtkinter.CTkFont(family="Segoe UI", size=18))
            empty_text.pack(anchor="w")
            empty_query = customtkinter.CTkLabel(empty, text=self.last_search_query, font=customtkinter.CTkFont(family="Segoe UI", size=19, weight="bold"), text_color=palette["text_primary"])
            empty_query.pack(anchor="w", pady=(4, 0))
            action = customtkinter.CTkButton(empty, text="Back To Trending", command=lambda: self.load_page(1), image=self.home_icon, compound="left", fg_color=palette["accent"], hover_color=palette["accent_hover"])
            action.pack(anchor="w", pady=(12, 0))
            return empty
        if self.hide_downloaded and items:
            empty_text = customtkinter.CTkLabel(empty, text="All sounds in this view are already downloaded.", font=customtkinter.CTkFont(family="Segoe UI", size=18))
            empty_text.pack(anchor="w")
            return empty
        empty_text = customtkinter.CTkLabel(empty, text="No sounds found for this view.", font=customtkinter.CTkFont(family="Segoe UI", size=18))
        empty_text.pack(anchor="w")
        action = customtkinter.CTkButton(empty, text="Reload Current View", command=self.reload_current_view, image=self.search_icon, compound="left", fg_color=palette["accent"], hover_color=palette["accent_hover"])
        action.pack(anchor="w", pady=(12, 0))
        return empty

    def _create_main_row(self, _master, item, _index):
        palette = current_palette()
        file_path = target_path_for(self.download_dir, item["title"])
        menu = RowContextMenu(self.app)
        actions = [("Play", lambda current=item: self.play_sound(current))]
        if file_path.exists():
            actions.extend([
                ("Reveal", lambda current=file_path: os.startfile(str(current))),
                ("Rename", lambda current=file_path: self.rename_downloaded_item(current)),
                ("Delete", lambda current=file_path: self.delete_downloaded_item(current)),
            ])
        else:
            actions.append(("Download", lambda current=item: self.download_item(current)))
            actions.append(("Open Downloads Folder", self.open_download_folder))
        actions.append(("Copy Path", lambda current=file_path: self.copy_path_to_clipboard(current)))
        menu.set_actions(actions)
        return SoundRow(
            self.list_frame.canvas,
            item=item,
            play_command=lambda current=item: self.play_sound(current),
            download_command=lambda current=item: self.download_item(current),
            icon_image=self.download_icon,
            play_icon=self.play_icon,
            palette=palette,
            context_menu=menu,
        )

    def _update_main_row(self, row, item, _index):
        self.row_widgets[item["url"]] = row
        if item["url"] in self.active_downloads:
            row.set_downloading(True)
        else:
            row.set_downloaded(target_path_for(self.download_dir, item["title"]).exists())

    def render_items(self, items, status_message):
        self.current_items = list(items)
        visible_items = [
            item for item in items
            if not self.hide_downloaded or not target_path_for(self.download_dir, item["title"]).exists()
        ]
        if self.hide_downloaded:
            self.result_var.set(f"{len(visible_items)} shown • {len(items)} sounds total")
        else:
            self.result_var.set(f"{len(items)} sounds total")
        self.set_status(status_message)
        self.clear_list()
        palette = current_palette()

        if not visible_items:
            if self.current_mode == "page" and self.hide_downloaded and items:
                next_page_number = self.page_no + 1
                self.set_status(
                    f"All sounds on page {self.page_no} are already downloaded. Loading page {next_page_number}..."
                )
                self.load_page(next_page_number)
                return
            if self.hide_downloaded and items:
                self.result_var.set(f"0 shown • {len(items)} sounds total")
            else:
                self.result_var.set("0 sounds total")
            empty = customtkinter.CTkFrame(
                self.list_frame,
                fg_color="transparent",
            )
            empty.grid(row=0, column=0, padx=14, pady=22, sticky="w")

            empty_icon = customtkinter.CTkLabel(empty, text="", image=self.search_empty_icon)
            empty_icon.pack(anchor="w", pady=(0, 10))

            if self.current_mode == "search" and self.last_search_query:
                empty_text = customtkinter.CTkLabel(
                    empty,
                    text="No sounds found for this search result:",
                    font=customtkinter.CTkFont(family="Segoe UI", size=18),
                )
                empty_text.pack(anchor="w")

                empty_query = customtkinter.CTkLabel(
                    empty,
                    text=self.last_search_query,
                    font=customtkinter.CTkFont(family="Segoe UI", size=19, weight="bold"),
                    text_color=palette["text_primary"],
                )
                empty_query.pack(anchor="w", pady=(4, 0))
            elif self.hide_downloaded and items:
                empty_text = customtkinter.CTkLabel(
                    empty,
                    text="All sounds in this view are already downloaded.",
                    font=customtkinter.CTkFont(family="Segoe UI", size=18),
                )
                empty_text.pack(anchor="w")
            else:
                empty_text = customtkinter.CTkLabel(
                    empty,
                    text="No sounds found for this view.",
                    font=customtkinter.CTkFont(family="Segoe UI", size=18),
                )
                empty_text.pack(anchor="w")
            return

        for index, item in enumerate(visible_items):
            row = SoundRow(
                self.list_frame,
                item=item,
                play_command=lambda current=item: self.play_sound(current),
                download_command=lambda current=item: self.download_item(current),
                icon_image=self.download_icon,
                play_icon=self.play_icon,
                palette=palette,
            )
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=5)
            self.row_widgets[item["url"]] = row
            if item["url"] in self.active_downloads:
                row.set_downloading(True)
            else:
                row.set_downloaded(target_path_for(self.download_dir, item["title"]).exists())

    def load_page(self, page_number):
        def _worker():
            try:
                items = getPage(page_number, region=self.server_region, base_url=self.server_base_url)
                self.current_mode = "page"
                self.page_no = page_number
                self.app.after(0, self.page_var.set, f"Page {self.page_no}")
                self.app.after(0, self.list_title_var.set, f"Page {self.page_no}")
                self.app.after(
                    0,
                    self.render_items,
                    items,
                    f"Loaded page {self.page_no}",
                )
                if self.auto_download_page_on_load == page_number:
                    self.auto_download_page_on_load = None
                    self.app.after(0, self.download_all_current)
            except Exception as exc:
                if self.auto_download_page_on_load == page_number:
                    self.auto_download_page_on_load = None
                self.app.after(0, self.set_status, f"Unable to load page: {exc}")

        self.page_var.set(f"Page {page_number} • Loading...")
        self.set_loading_state(f"Loading page {page_number}...", "Loading page...")
        self.page_var.set(f"Page {page_number}")
        self.list_title_var.set(f"Page {page_number}")
        threading.Thread(target=_worker, daemon=True).start()

    def search(self, query=None):
        query = (query if query is not None else self.search_entry.get()).strip()
        if not query:
            self.set_status("Enter a search term first.")
            return

        def _worker():
            try:
                items = searchq(query, base_url=self.server_base_url)
                self.current_mode = "search"
                self.last_search_query = query
                self.app.after(0, self.page_var.set, "Search Results")
                self.app.after(0, self.list_title_var.set, "Search Results")
                self.app.after(
                    0,
                    self.render_items,
                    items,
                    f"Loaded search results for '{query}'",
                )
            except Exception as exc:
                self.app.after(0, self.set_status, f"Search failed on {self.server_base_url}: {exc}")

        self.page_var.set("Search Results • Loading...")
        self.set_loading_state(f"Searching for '{query}'...", "Searching...")
        self.page_var.set("Search Results")
        self.list_title_var.set("Search Results")
        threading.Thread(target=_worker, daemon=True).start()

    def prefetch_page(self, page_number):
        if page_number <= 0 or page_number in self.prefetched_pages or page_number in self.page_prefetching:
            return

        def _worker():
            try:
                items = getPage(page_number, region=self.server_region, base_url=self.server_base_url)
            except Exception:
                return
            finally:
                self.page_prefetching.discard(page_number)
            self.prefetched_pages[page_number] = items

        self.page_prefetching.add(page_number)
        threading.Thread(target=_worker, daemon=True).start()

    def render_items(self, items, status_message):
        self.current_items = list(items)
        visible_items = [
            item for item in items
            if not self.hide_downloaded or not target_path_for(self.download_dir, item["title"]).exists()
        ]
        self.visible_items = list(visible_items)
        if self.hide_downloaded:
            self.result_var.set(f"{len(visible_items)} shown • {len(items)} sounds total")
        else:
            self.result_var.set(f"{len(items)} sounds total")
        self.set_status(status_message)
        self.clear_list()

        if not visible_items:
            if self.hide_downloaded and items:
                self.result_var.set(f"0 shown • {len(items)} sounds total")
            else:
                self.result_var.set("0 sounds total")
            self.list_frame.set_empty_widget(self._build_main_empty_state(items))
            return

        self.list_frame.set_items(
            visible_items,
            self._create_main_row,
            row_updater=self._update_main_row,
            item_key=lambda item: item["url"],
        )
        if self.current_mode == "page":
            self.prefetch_page(self.page_no + 1)

    def load_page(self, page_number):
        token = self.page_fetch_tokens.get(page_number, 0) + 1
        self.page_fetch_tokens[page_number] = token

        def _finish(items):
            if self.page_fetch_tokens.get(page_number) != token:
                return
            self.current_mode = "page"
            self.page_no = page_number
            self.page_var.set(f"Page {self.page_no}")
            self.list_title_var.set(f"Page {self.page_no}")
            self.render_items(items, f"Loaded page {self.page_no}")
            if self.auto_download_page_on_load == page_number:
                self.auto_download_page_on_load = None
                self.download_all_current()

        def _fail(exc):
            if self.auto_download_page_on_load == page_number:
                self.auto_download_page_on_load = None
            self.set_status(
                f"Unable to load page {page_number} from {self.server_base_url} [{self.server_region.upper()}]: {exc}"
            )

        def _worker():
            try:
                items = getPage(page_number)
                self.prefetched_pages[page_number] = items
                self.app.after(0, _finish, items)
            except Exception as exc:
                self.app.after(0, _fail, exc)

        self.page_var.set(f"Page {page_number} • Loading...")
        self.set_loading_state(f"Loading page {page_number}...", "Loading page...")
        self.page_var.set(f"Page {page_number}")
        self.list_title_var.set(f"Page {page_number}")
        cached = self.prefetched_pages.pop(page_number, None)
        if cached is not None:
            self.app.after(0, _finish, cached)
            return
        threading.Thread(target=_worker, daemon=True).start()

    def render_items(self, items, status_message):
        self.current_items = list(items)
        visible_items = [
            item for item in items
            if not self.hide_downloaded or not target_path_for(self.download_dir, item["title"]).exists()
        ]
        self.visible_items = list(visible_items)
        if self.hide_downloaded:
            self.result_var.set(f"{len(visible_items)} shown • {len(items)} sounds total")
        else:
            self.result_var.set(f"{len(items)} sounds total")
        self.set_status(status_message)
        self.clear_list()

        if not visible_items:
            if self.current_mode == "page" and self.hide_downloaded and items:
                next_page_number = self.page_no + 1
                self.set_status(f"All sounds on page {self.page_no} are already downloaded. Loading page {next_page_number}...")
                self.load_page(next_page_number)
                return
            if self.hide_downloaded and items:
                self.result_var.set(f"0 shown • {len(items)} sounds total")
            else:
                self.result_var.set("0 sounds total")
            self.list_frame.set_empty_widget(self._build_main_empty_state(items))
            return

        self.list_frame.set_items(
            visible_items,
            self._create_main_row,
            row_updater=self._update_main_row,
            item_key=lambda item: item["url"],
        )
        if self.current_mode == "page":
            self.prefetch_page(self.page_no + 1)

    def reload_current_view(self):
        if self.current_mode == "search":
            self.search(self.last_search_query)
        else:
            self.load_page(self.page_no)

    def next_page(self):
        self.load_page(self.page_no + 1)

    def prev_page(self):
        if self.page_no <= 1:
            self.set_status("You are already on the first page.")
            return
        self.load_page(self.page_no - 1)

    def open_download_folder(self):
        ensure_directory(self.download_dir)
        os.startfile(str(self.download_dir.resolve()))

    def on_batch_complete(self, message: str):
        self.set_status(message)
        self.batch_window = None
        self.render_items(self.current_items, self.status_var.get())

    def download_all_current(self):
        if not self.current_items:
            self.set_status("Nothing to download in the current view.")
            return
        if self.current_mode == "page" and all(
            target_path_for(self.download_dir, item["title"]).exists()
            for item in self.current_items
        ):
            next_page_number = self.page_no + 1
            self.set_status(f"All sounds on page {self.page_no} are already downloaded. Opening page {next_page_number}...")
            self.load_page(next_page_number)
            return
        if self.batch_window is not None and self.batch_window.winfo_exists():
            self.batch_window.focus()
            return
        next_page_callback = self.download_next_page if self.current_mode == "page" else None
        self.batch_window = DownloadProgressWindow(
            self.app,
            self.current_items,
            self.on_batch_complete,
            self.download_dir,
            on_next_page=next_page_callback,
        )

    def download_next_page(self, auto_download: bool = False):
        if self.current_mode != "page":
            return
        next_page_number = self.page_no + 1
        self.batch_window = None
        self.auto_download_page_on_load = next_page_number if auto_download else None
        self.load_page(next_page_number)

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.focus()
            return
        self.settings_window = SettingsWindow(self)

    def open_inventory(self):
        if self.inventory_window is not None and self.inventory_window.winfo_exists():
            self.inventory_window.focus()
            self.inventory_window.refresh_inventory()
            return
        self.inventory_window = InventoryWindow(self)

    def apply_appearance_mode(self, mode: str, persist: bool = True):
        customtkinter.set_appearance_mode(mode)
        self.settings["appearance_mode"] = mode
        if persist:
            save_settings(self.settings)
        for child in self.app.winfo_children():
            child.destroy()
        self.app.configure(fg_color=current_palette()["app_bg"])
        self.build_menu()
        self.build_layout()
        self.render_items(self.current_items, self.status_var.get())

    def run(self):
        self.app.mainloop()


if __name__ == "__main__":
    MyInstantsApp().run()
