import sys

from timechart.core.singleton import Singleton


class IdleDetector(metaclass=Singleton):
    def __init__(self):
        if sys.platform == 'linux':
            from timechart.core.linux import idle_detector_linux
            self.is_idle = idle_detector_linux.is_idle
        elif sys.platform == 'win32':
            from timechart.core.win32 import idle_detector_win32
            self.is_idle = idle_detector_win32.is_idle

    def is_idle(self) -> bool:
        return self.is_idle()

