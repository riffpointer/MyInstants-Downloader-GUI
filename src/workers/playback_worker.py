from PySide6.QtCore import QThread, QObject, Signal


class PlaybackSignals(QObject):
    finished = Signal()
    error = Signal(str)


class PlaybackWorker(QThread):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.signals = PlaybackSignals()

    def run(self):
        try:
            from playsound import playsound

            playsound(self.url)
            self.signals.finished.emit()
        except Exception as exc:
            self.signals.error.emit(str(exc))
