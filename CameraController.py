import os
import time
import base64
import logging
import numpy as np
import cv2
import PySpin

from PySide6.QtCore import QObject, Signal, Property, QThread, Slot, QTimer, QBuffer, QMutex, QMutexLocker, Qt
from PySide6.QtGui import QImage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CameraWorker(QThread):
    """Поток для захвата кадров с FLIR камеры в 8-битном режиме"""
    frame_ready = Signal(QImage)
    frame_data_ready = Signal(str)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    info_updated = Signal(str, str)
    fps_updated = Signal(float)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.system = None
        self.running = False
        self.mutex = QMutex()
        self.last_valid_frame = None
        
        # Базовые настройки
        self.target_width = 1936
        self.target_height = 1464
        self.target_fps = 30  # Пробуем 30 FPS, будем оптимизировать
        
        # Параметры камеры
        self.auto_exposure = False
        self.auto_gain = True
        self.exposure_time = 20000  # 20000 мкс
        self.gain = 15.0
        self.gamma = 0.7
        self.gamma_enable = True
        
        # Оптимизация производительности
        self.packet_size = 9000  # Jumbo frames для GigE
        self.packet_delay = 2000  # Минимальная задержка между пакетами (нс)
        self.auto_packet_size = False  # Отключаем авто-настройку размера пакета