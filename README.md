# MyInstants Downloader

![BADGE](https://badgen.net/github/release/Shagnikpaul/MyInstants-Downloader-GUI)
![B2](https://img.shields.io/github/downloads/riffpointer/MyInstants-Downloader-GUI/total)

A Qt-based GUI utility to play and download sounds from [myinstants.com](https://www.myinstants.com/en/index/in/).

## What's new in 2.0?
- Rebuilt the app around PySide6 with a cleaner toolbar and menu layout.
- Added batch download progress with skipping for already-downloaded files.
- Added next-page prompting when a page is fully downloaded.
- Added per-row playback state, download progress, and a cleaner inventory flow.
- Added settings for download folder, theme, and concurrent download count.
- Improved search behavior, empty states, and focus handling across dialogs.

## Run
For now, executable files are published for Windows only. But you can run it manually by cloning the repo, installing the dependencies from `requirements.txt`, and running the program manually with `py main.py`.

### Portable ZIP
Download the latest release ZIP, extract it, and run `MyInstantsDownloader.exe`.

### Installer
Download the latest installer from the Releases page and run it normally.

## Project Layout (for devs)
- `main.py` is the Qt entrypoint.
- `src/ui/` contains the main window and dialogs.
- `src/workers/` contains scraping, playback, and download workers.
- `resources/` contains bundled icons and audio assets.
- `scripts/build_exe.py` builds the packaged app.
- PyInstaller outputs are written to `scripts/build/` and `scripts/dist/`.

## Notes
- Downloaded files are saved in the `downloads` folder next to the app.
- The inventory window shows saved files and supports rename/delete actions.
- (Coming soon) You can drag and drop sound effects from within the inventory window.
- (Coming soon) Support for more services.

## Screenshot
Main screen:

<img width="1366" height="728" alt="image" src="https://github.com/user-attachments/assets/0b55c19c-de55-4343-bae6-9ea76aa4cea1" />

## License
Licensed under the MIT License.

## Contributors
- https://github.com/Shagnikpaul - Author
- https://github.com/riffpointer - PySide6 port