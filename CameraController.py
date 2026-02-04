# -*- coding: utf-8 -*-

"""
Camera Controller Module.
Версия сборки: 3.0 (Pixel Format Support)
"""

import os
import time
import logging
import json
from logging.handlers import RotatingFileHandler
import numpy as np
import cv2
import PySpin

from PySide6.QtCore import (
    QObject, Signal, Property, QThread, 
    Slot, QMutex, QMutexLocker
)
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickImageProvider


# --- LOGGING SETUP ---
def setup_logger():
    logger = logging.getLogger("FLIR_System")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_debug.log")
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    if logger.hasHandlers(): logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger

logger = setup_logger()


class LiveImageProvider(QQuickImageProvider):
    """Zero-Copy Image Provider."""
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
    """Backend Worker: управляет железом и потоком данных."""
    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    fps_updated = Signal(float)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.system = None
        self.running = False
        
        # Internal State
        self.exposure_time = 20000.0
        self.gain = 15.0
        self.wb_red = 1.5
        self.pixel_format_str = "Mono8" # Default
        
        self.packet_size = 9000
        self._lock = QMutex() 

    def run(self):
        try:
            logger.info("Worker: Initializing System")
            self.system = PySpin.System.GetInstance()
            cam_list = self.system.GetCameras()
            
            if cam_list.GetSize() == 0:
                self.error_occurred.emit("Камеры не найдены")
                cam_list.Clear()
                self.system.ReleaseInstance()
                return

            self.camera = cam_list.GetByIndex(0)
            self.camera.Init()
            
            self._apply_initial_settings()
            
            self.camera.BeginAcquisition()
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            fps_counter = 0
            fps_timer = time.time()
            
            while self.running:
                # Блокировка нужна, чтобы не читать кадр, пока мы меняем PixelFormat
                with QMutexLocker(self._lock):
                    if not self.running: break
                    
                    try:
                        # Timeout 1000ms. Если меняем формат, тут может выпасть timeout, это нормально.
                        image_result = self.camera.GetNextImage(1000)
                        
                        if image_result.IsIncomplete():
                            image_result.Release()
                            continue

                        qimage = self._convert_to_qimage(image_result)
                        if not qimage.isNull():
                            self.frame_ready.emit(qimage)
                            fps_counter += 1
                        
                        image_result.Release()
                        
                    except PySpin.SpinnakerException as ex:
                        # Игнорируем таймауты, которые случаются при смене настроек
                        if "SPINNAKER_ERR_TIMEOUT" not in str(ex):
                            logger.debug(f"Spinnaker Warning: {ex}")
                        continue
                    except Exception as e:
                        logger.error(f"Frame Error: {e}")
                        continue

                # FPS Calculation outside lock
                current_time = time.time()
                if current_time - fps_timer >= 1.0:
                    fps = fps_counter / (current_time - fps_timer)
                    self.fps_updated.emit(fps)
                    fps_counter = 0
                    fps_timer = current_time

        except Exception as e:
            logger.critical(f"Critical Worker Crash: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    def _apply_initial_settings(self):
        """Применяем настройки ПЕРЕД стартом потока."""
        try:
            # 1. Packet Size
            try:
                nodemap = self.camera.GetTLStreamNodeMap()
                node = PySpin.CIntegerPtr(nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(min(node.GetMax(), self.packet_size))
            except: pass

            # 2. Pixel Format (Critical Step)
            self.set_pixel_format(self.pixel_format_str, force_restart=False)

            # 3. Sensors
            self.set_exposure(self.exposure_time)
            self.set_gain(self.gain)
            self.set_wb_red(self.wb_red)
            
        except Exception as e:
            logger.error(f"Setup Error: {e}")

    def _convert_to_qimage(self, image_result):
        """Конвертация Raw буфера в QImage."""
        try:
            image_data = image_result.GetNDArray()
            # Получаем реальный формат кадра (он может отличаться от запрошенного, если ошибка)
            current_format = image_result.GetPixelFormat() 
            
            rgb = None
            
            # Логика демозаики и конверсии
            if current_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB)
            
            elif current_format == PySpin.PixelFormat_BayerRG8:
                # BayerRG -> RGB
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2RGB)
                
            elif current_format == PySpin.PixelFormat_RGB8:
                rgb = image_data # Уже RGB
                
            elif current_format == PySpin.PixelFormat_BGR8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)
                
            else:
                # Fallback для неизвестных форматов (считаем Mono)
                if len(image_data.shape) == 2:
                    rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB)
                else:
                    return QImage()

            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            return img.copy()

        except Exception as e:
            logger.error(f"Conversion Error: {e}")
            return QImage()

    # --- HARDWARE CONTROL METHODS ---

    def set_pixel_format(self, format_name, force_restart=True):
        """
        Меняет формат пикселей.
        ВАЖНО: Требует остановки Acquisition!
        """
        if not self.camera: return

        with QMutexLocker(self._lock): # Блокируем цикл run
            try:
                was_streaming = self.camera.IsStreaming()
                
                # 1. Stop Stream if needed
                if was_streaming and force_restart:
                    self.camera.EndAcquisition()
                
                # 2. Set Node
                nodemap = self.camera.GetNodeMap()
                node_pf = PySpin.CEnumerationPtr(nodemap.GetNode("PixelFormat"))
                
                if PySpin.IsAvailable(node_pf) and PySpin.IsWritable(node_pf):
                    entry = node_pf.GetEntryByName(format_name)
                    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
                        node_pf.SetIntValue(entry.GetValue())
                        self.pixel_format_str = format_name
                        logger.info(f"Sensor Format set to: {format_name}")
                    else:
                        logger.warning(f"Format {format_name} not supported by sensor")
                
                # 3. Restart Stream
                if was_streaming and force_restart:
                    self.camera.BeginAcquisition()
                    
            except Exception as e:
                logger.error(f"Failed to change pixel format: {e}")

    def set_gain(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gain"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
            except: pass

    def set_wb_red(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                # Ensure Auto WB is off
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())
                
                # Select Red Channel
                selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                if PySpin.IsAvailable(selector) and PySpin.IsWritable(selector):
                    selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                
                # Set Value
                ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                if PySpin.IsAvailable(ratio) and PySpin.IsWritable(ratio):
                    ratio.SetValue(value)
            except: pass

    def set_exposure(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                exp_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exp_auto) and PySpin.IsWritable(exp_auto):
                    exp_auto.SetIntValue(exp_auto.GetEntryByName("Off").GetValue())
                
                node = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    val = max(node.GetMin(), min(value, node.GetMax()))
                    node.SetValue(val)
                    self.exposure_time = val
            except: pass

    def capture_photo(self, path, fmt, q):
        pass # Placeholder

    def _cleanup(self):
        if self.camera:
            try:
                if self.camera.IsStreaming():
                    self.camera.EndAcquisition()
                self.camera.DeInit()
            except: pass
            del self.camera
        if self.system:
            self.system.ReleaseInstance()
    
    def stop(self):
        self.running = False
        self.wait()


class CameraController(QObject):
    """UI Controller."""
    frameChanged = Signal()
    statusChanged = Signal()
    currentFpsChanged = Signal()
    imagePathChanged = Signal()
    
    # Settings Signals
    gainChanged = Signal()
    exposureChanged = Signal()
    wbRedChanged = Signal()
    pixelFormatChanged = Signal() # NEW

    def __init__(self):
        super().__init__()
        self._status = "Готов"
        self._currentFps = 0.0
        self._image_path = ""
        
        # MAPPING: Index <-> String name
        self.FORMAT_MAP = {0: "Mono8", 1: "RGB8", 2: "BayerRG8"}
        self.FORMAT_MAP_REV = {"Mono8": 0, "RGB8": 1, "BayerRG8": 2}
        
        self.DEFAULT_CONFIG = {
            "exposure": 20000.0,
            "gain": 15.0,
            "wb_red": 1.5,
            "pixel_format_idx": 0 # Default Mono8
        }
        
        self.CONFIG_FILE = os.path.join(os.path.dirname(__file__), "camera_preset.json")
        
        # Init Values
        self._gain_value = self.DEFAULT_CONFIG["gain"]
        self._wb_red_value = self.DEFAULT_CONFIG["wb_red"]
        self._exposure_value = self.DEFAULT_CONFIG["exposure"]
        self._pixel_format_index = self.DEFAULT_CONFIG["pixel_format_idx"]
        
        self.worker = None
        self.provider = None

    def set_image_provider(self, provider):
        self.provider = provider

    @Property(str, notify=imagePathChanged)
    def imagePath(self): return self._image_path

    @Slot()
    def start_camera(self):
        if self.worker and self.worker.isRunning(): return
        self.worker = CameraWorker()
        
        # Передаем параметры в воркер
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        self.worker.pixel_format_str = self.FORMAT_MAP.get(self._pixel_format_index, "Mono8")
        
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.status_changed.connect(self._update_status)
        self.worker.fps_updated.connect(self._update_fps)
        self.worker.start()

    @Slot()
    def stop_camera(self):
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

    # --- UI Properties ---

    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property(float, notify=currentFpsChanged)
    def currentFps(self): return self._currentFps

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

    # --- NEW PROPERTY: PIXEL FORMAT ---
    @Property(int, notify=pixelFormatChanged)
    def pixelFormatIndex(self): 
        return self._pixel_format_index
    
    @pixelFormatIndex.setter
    def pixelFormatIndex(self, val):
        if self._pixel_format_index != val:
            self._pixel_format_index = val
            format_str = self.FORMAT_MAP.get(val, "Mono8")
            logger.info(f"UI Request: Set format to {format_str}")
            
            if self.worker: 
                self.worker.set_pixel_format(format_str)
            
            self.pixelFormatChanged.emit()

    # --- PRESETS MANAGEMENT ---

    @Slot()
    def reset_defaults(self):
        self.exposureValue = self.DEFAULT_CONFIG["exposure"]
        self.gainValue = self.DEFAULT_CONFIG["gain"]
        self.wbRedValue = self.DEFAULT_CONFIG["wb_red"]
        self.pixelFormatIndex = self.DEFAULT_CONFIG["pixel_format_idx"]
        self._update_status("Сброс настроек")

    @Slot()
    def save_preset(self):
        config = {
            "exposure": self._exposure_value,
            "gain": self._gain_value,
            "wb_red": self._wb_red_value,
            "pixel_format_idx": self._pixel_format_index # Save format
        }
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
            self._update_status("Пресет сохранен")
        except Exception as e:
            logger.error(f"Save failed: {e}")

    @Slot()
    def load_preset(self):
        if not os.path.exists(self.CONFIG_FILE):
            self._update_status("Нет пресетов")
            return
        try:
            with open(self.CONFIG_FILE, 'r') as f:
                config = json.load(f)
            
            if "exposure" in config: self.exposureValue = config["exposure"]
            if "gain" in config: self.gainValue = config["gain"]
            if "wb_red" in config: self.wbRedValue = config["wb_red"]
            if "pixel_format_idx" in config: self.pixelFormatIndex = config["pixel_format_idx"]
            
            self._update_status("Пресет загружен")
        except Exception as e:
            logger.error(f"Load failed: {e}")

    @Slot(str, str, int)
    def capture_photo(self, path, fmt, q):
        pass