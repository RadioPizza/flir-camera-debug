# -*- coding: utf-8 -*-

"""
Camera Controller Module.

Обеспечивает взаимодействие с FLIR камерой через PySpin SDK,
обработку изображений и интеграцию с QML через сигналы/слоты.
"""

import os
import time
import logging
import json  # [Добавлено] Для работы с конфигами
from logging.handlers import RotatingFileHandler
import platform
import numpy as np
import cv2
import PySpin

from PySide6.QtCore import (
    QObject, Signal, Property, QThread, 
    Slot, QMutex, QMutexLocker, Qt, QSize
)
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickImageProvider


# --- НАСТРОЙКА ПРОДВИНУТОГО ЛОГИРОВАНИЯ ---
def setup_logger():
    logger = logging.getLogger("FLIR_System")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    log_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        "camera_debug.log"
    )
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=5*1024*1024, 
        backupCount=3, 
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


logger = setup_logger()


class LiveImageProvider(QQuickImageProvider):
    """Провайдер изображений для QML (Direct Memory Access)."""
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._current_image = QImage(800, 600, QImage.Format_RGB888)
        self._current_image.fill(QColor("black"))
        self.mutex = QMutex()

    def requestImage(self, id, size, requestedSize):
        with QMutexLocker(self.mutex):
            return self._current_image
            
    def update_image(self, image):
        with QMutexLocker(self.mutex):
            if not image.isNull():
                self._current_image = image


class CameraWorker(QThread):
    """Рабочий поток захвата видео (Backend)."""
    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    info_updated = Signal(str, str)
    fps_updated = Signal(float)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.system = None
        self.running = False
        
        # Параметры по умолчанию
        self.exposure_time = 20000.0
        self.gain = 15.0
        self.wb_red = 1.5 
        
        self.packet_size = 9000
        logger.debug("CameraWorker инициализирован.")

    def run(self):
        try:
            logger.info("=== НАЧАЛО СЕССИИ ЗАХВАТА ===")
            self.system = PySpin.System.GetInstance()
            cam_list = self.system.GetCameras()
            
            if cam_list.GetSize() == 0:
                self.error_occurred.emit("Камеры не найдены")
                cam_list.Clear()
                self.system.ReleaseInstance()
                return

            self.camera = cam_list.GetByIndex(0)
            self.camera.Init()
            
            self._setup_camera()
            
            self.camera.BeginAcquisition()
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            fps_counter = 0
            fps_timer = time.time()
            
            while self.running:
                try:
                    image_result = self.camera.GetNextImage(2000)
                    if image_result.IsIncomplete():
                        image_result.Release()
                        continue

                    qimage = self._convert_to_qimage(image_result)
                    if not qimage.isNull():
                        self.frame_ready.emit(qimage)
                        fps_counter += 1
                    
                    image_result.Release()
                    
                    current_time = time.time()
                    if current_time - fps_timer >= 1.0:
                        fps = fps_counter / (current_time - fps_timer)
                        self.fps_updated.emit(fps)
                        fps_counter = 0
                        fps_timer = current_time
                        
                except PySpin.SpinnakerException as ex:
                    logger.error(f"Spinnaker Exception: {ex}")
                    continue
                except Exception:
                    continue

        except Exception as e:
            logger.critical(f"Critical Worker Crash: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()
            logger.info("=== КОНЕЦ СЕССИИ ЗАХВАТА ===")

    def _setup_camera(self):
        try:
            # Настройка пакетов
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                packet_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_node) and PySpin.IsWritable(packet_node):
                    val = min(packet_node.GetMax(), self.packet_size)
                    packet_node.SetValue(val)
                
                buffer_mode = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(buffer_mode) and PySpin.IsWritable(buffer_mode):
                    buffer_mode.SetIntValue(buffer_mode.GetEntryByName("NewestOnly").GetValue())
            except Exception: 
                pass

            # Применяем значения сенсоров
            self.set_exposure(self.exposure_time)
            self.set_gain(self.gain)
            self.set_wb_red(self.wb_red)
            
        except Exception as e:
            logger.error(f"Ошибка настройки камеры: {e}")

    def _convert_to_qimage(self, image_result):
        try:
            image_data = image_result.GetNDArray()
            pixel_format = image_result.GetPixelFormat()
            rgb = None
            
            if pixel_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerRG8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif pixel_format == PySpin.PixelFormat_RGB8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_RGB2BGR)
            elif pixel_format == PySpin.PixelFormat_BGR8:
                rgb = image_data
            else:
                if len(image_data.shape) == 2: 
                    rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
                else: 
                    return QImage()

            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            return img.copy() 
        except Exception:
            return QImage()

    # --- СЕТТЕРЫ (Hardware Control) ---

    def set_gain(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gain"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
            except Exception as e:
                logger.error(f"Failed to set Gain: {e}")

    def set_wb_red(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())

                selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                if PySpin.IsAvailable(selector) and PySpin.IsWritable(selector):
                    selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                
                ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                if PySpin.IsAvailable(ratio) and PySpin.IsWritable(ratio):
                    ratio.SetValue(value)
            except Exception as e:
                logger.error(f"Failed to set WB: {e}")

    def set_exposure(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exposure_auto) and PySpin.IsWritable(exposure_auto):
                    exposure_auto.SetIntValue(exposure_auto.GetEntryByName("Off").GetValue())
                
                exposure_time = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(exposure_time) and PySpin.IsWritable(exposure_time):
                    val = max(exposure_time.GetMin(), min(value, exposure_time.GetMax()))
                    exposure_time.SetValue(val)
                    self.exposure_time = val
            except Exception as e:
                logger.error(f"Failed to set Exposure: {e}")

    def capture_photo(self, file_path, format, quality):
        pass 

    def _cleanup(self):
        if self.camera:
            self.camera.EndAcquisition()
            self.camera.DeInit()
            del self.camera
        if self.system:
            self.system.ReleaseInstance()
    
    def stop(self):
        self.running = False
        self.wait()


class CameraController(QObject):
    """
    Контроллер приложения (UI Logic).
    """
    frameChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()
    currentFpsChanged = Signal()
    imagePathChanged = Signal()
    
    # [Добавлено] Сигналы уведомления для синхронизации UI при загрузке пресета
    gainChanged = Signal()
    exposureChanged = Signal()
    wbRedChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "Готов"
        self._currentFps = 0.0
        self._camera_info = {}
        self._image_path = ""
        
        # Значения по умолчанию
        self.DEFAULT_CONFIG = {
            "exposure": 20000.0,
            "gain": 15.0,
            "wb_red": 1.5
        }
        
        self.CONFIG_FILE = os.path.join(os.path.dirname(__file__), "camera_preset.json")
        
        # Инициализация текущих значений дефолтными
        self._gain_value = self.DEFAULT_CONFIG["gain"]
        self._wb_red_value = self.DEFAULT_CONFIG["wb_red"]
        self._exposure_value = self.DEFAULT_CONFIG["exposure"]
        
        self.worker = None
        self.provider = None
        
        logger.debug("CameraController initialized")

    def set_image_provider(self, provider):
        self.provider = provider

    @Property(str, notify=imagePathChanged)
    def imagePath(self): return self._image_path

    @Slot()
    def start_camera(self):
        logger.info("UI: Start requested")
        if self.worker and self.worker.isRunning(): return
        
        self.worker = CameraWorker()
        
        # Передаем текущие параметры
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.status_changed.connect(self._update_status)
        self.worker.fps_updated.connect(self._update_fps)
        self.worker.start()

    @Slot()
    def stop_camera(self):
        logger.info("UI: Stop requested")
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._update_status("Остановлено")

    def _on_frame_ready(self, qimage):
        if self.provider:
            self.provider.update_image(qimage)
            self._image_path = f"image://live/frame_{time.time()}"
            self.imagePathChanged.emit()

    def _update_status(self, msg):
        self._status = msg
        self.statusChanged.emit()

    def _update_fps(self, fps):
        self._currentFps = fps
        self.currentFpsChanged.emit()

    # --- QML Свойства ---

    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property(float, notify=currentFpsChanged)
    def currentFps(self): return self._currentFps

    @Property('QVariantMap', notify=infoChanged)
    def cameraInfo(self): return self._camera_info
    
    # [Обновлено] Сеттеры теперь проверяют изменение и эмиссируют сигнал
    @Property(float, notify=gainChanged)
    def gainValue(self): return self._gain_value
    
    @gainValue.setter
    def gainValue(self, val):
        if self._gain_value != val:
            self._gain_value = val
            if self.worker: self.worker.set_gain(val)
            self.gainChanged.emit()

    @Property(float, notify=wbRedChanged)
    def wbRedValue(self): return self._wb_red_value
    
    @wbRedValue.setter
    def wbRedValue(self, val):
        if self._wb_red_value != val:
            self._wb_red_value = val
            if self.worker: self.worker.set_wb_red(val)
            self.wbRedChanged.emit()

    @Property(float, notify=exposureChanged)
    def exposureValue(self): return self._exposure_value
    
    @exposureValue.setter
    def exposureValue(self, val):
        if self._exposure_value != val:
            self._exposure_value = val
            if self.worker: self.worker.set_exposure(val)
            self.exposureChanged.emit()

    # --- УПРАВЛЕНИЕ ПРЕСЕТАМИ ---

    @Slot()
    def reset_defaults(self):
        """Сброс к заводским настройкам."""
        logger.info("Protocol: Restore Default Settings")
        # Присваивание свойствам автоматически вызовет сеттеры и обновит камеру/UI
        self.exposureValue = self.DEFAULT_CONFIG["exposure"]
        self.gainValue = self.DEFAULT_CONFIG["gain"]
        self.wbRedValue = self.DEFAULT_CONFIG["wb_red"]
        self._update_status("Сброс настроек")

    @Slot()
    def save_preset(self):
        """Сохранение текущих настроек в JSON."""
        config = {
            "exposure": self._exposure_value,
            "gain": self._gain_value,
            "wb_red": self._wb_red_value
        }
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
            logger.info(f"Preset saved to {self.CONFIG_FILE}")
            self._update_status("Пресет сохранен")
        except Exception as e:
            logger.error(f"Save failed: {e}")
            self._update_status("Ошибка сохранения")

    @Slot()
    def load_preset(self):
        """Загрузка настроек из JSON."""
        if not os.path.exists(self.CONFIG_FILE):
            logger.warning("Preset file not found")
            self._update_status("Нет пресетов")
            return

        try:
            with open(self.CONFIG_FILE, 'r') as f:
                config = json.load(f)
            
            # Применяем настройки. Сеттеры обновят UI благодаря сигналам
            if "exposure" in config: self.exposureValue = config["exposure"]
            if "gain" in config: self.gainValue = config["gain"]
            if "wb_red" in config: self.wbRedValue = config["wb_red"]
            
            logger.info("Preset loaded successfully")
            self._update_status("Пресет загружен")
        except Exception as e:
            logger.error(f"Load failed: {e}")
            self._update_status("Ошибка загрузки")

    @Slot(str, str, int)
    def capture_photo(self, path, fmt, q):
        if self.worker:
            self.worker.capture_photo(path, fmt, q)