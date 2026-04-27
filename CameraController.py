# -*- coding: utf-8 -*-

"""
Camera Controller Module for FLIR Blackfly S.   
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
    Slot, QMutex, QMutexLocker, QUrl
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
    """Zero-Copy Image Provider для передачи кадров в QML."""
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
    """Backend Worker: управляет аппаратной частью камеры в отдельном потоке."""
    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    metrics_updated = Signal(float, float, float, float)
    resolution_updated = Signal(str)
    wb_red_calculated = Signal(float) # Сигнал для обновления ползунка АВТО

    def __init__(self):
        super().__init__()
        self.camera = None
        self.system = None
        self.running = False
        
        # Ручные параметры сенсора
        self.exposure_time = 20000.0
        self.gain = 10.0
        self.wb_red = 1.20
        self.gamma = 1.0
        self.wb_auto = False
        self.pixel_format_str = "BayerRG8"
        
        self.packet_size = 9000
        self._lock = QMutex() 

    def run(self):
        try:
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
            
            target_fps = 0.0
            try:
                nodemap = self.camera.GetNodeMap()
                w_node = PySpin.CIntegerPtr(nodemap.GetNode("Width"))
                h_node = PySpin.CIntegerPtr(nodemap.GetNode("Height"))
                if PySpin.IsAvailable(w_node) and PySpin.IsAvailable(h_node):
                    self.resolution_updated.emit(f"{w_node.GetValue()}x{h_node.GetValue()}")

                fps_node = PySpin.CFloatPtr(nodemap.GetNode("AcquisitionResultingFrameRate"))
                if PySpin.IsAvailable(fps_node):
                    target_fps = fps_node.GetValue()
            except Exception as e:
                logger.warning(f"Failed to read sensor metrics: {e}")

            self.camera.BeginAcquisition()
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            fps_counter = 0
            total_frames = 0
            start_time = time.time()
            fps_timer = start_time
            
            while self.running:
                with QMutexLocker(self._lock):
                    if not self.running: break
                    try:
                        image_result = self.camera.GetNextImage(1000)
                        if image_result.IsIncomplete():
                            image_result.Release()
                            continue

                        qimage = self._convert_to_qimage(image_result)
                        if not qimage.isNull():
                            self.frame_ready.emit(qimage)
                            fps_counter += 1
                            total_frames += 1
                        
                        image_result.Release()
                    except Exception as e:
                        continue

                current_time = time.time()
                if current_time - fps_timer >= 1.0:
                    current_fps = fps_counter / (current_time - fps_timer)
                    elapsed_total = current_time - start_time
                    avg_fps = total_frames / elapsed_total if elapsed_total > 0 else 0.0
                    efficiency = (current_fps / target_fps * 100.0) if target_fps > 0 else 0.0
                    
                    self.metrics_updated.emit(current_fps, avg_fps, target_fps, efficiency)
                    fps_counter = 0
                    fps_timer = current_time

        except Exception as e:
            logger.critical(f"Critical Worker Crash: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    def _apply_initial_settings(self):
        try:
            try:
                nodemap = self.camera.GetTLStreamNodeMap()
                node = PySpin.CIntegerPtr(nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(min(node.GetMax(), self.packet_size))
            except: pass

            self.set_pixel_format(self.pixel_format_str, force_restart=False)
            self.set_exposure(self.exposure_time) 
            self.set_gain(self.gain)
            self.set_gamma(self.gamma)
            
            # Если автобаланс выключен - применяем ручные настройки
            if not self.wb_auto:
                self.set_wb_red(self.wb_red)
                
            # Аппаратный автобаланс всегда выключаем, так как используем свой алгоритм
            try:
                nodemap = self.camera.GetNodeMap()
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())
            except: pass
            
        except Exception as e:
            logger.error(f"Setup Error: {e}")

    def _convert_to_qimage(self, image_result):
        try:
            image_data = image_result.GetNDArray()
            current_format = image_result.GetPixelFormat() 
            rgb = None
            
            if current_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB)
            elif current_format == PySpin.PixelFormat_BayerRG8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif current_format == PySpin.PixelFormat_RGB8:
                rgb = image_data
            else:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB) if len(image_data.shape) == 2 else image_data

            
            # === ГИБРИДНЫЙ АВТОБАЛАНС БЕЛОГО ===
            if hasattr(self, 'wb_auto') and self.wb_auto:
                current_time = time.time()
                if not hasattr(self, '_last_awb_time'):
                    self._last_awb_time = 0
                    
                if current_time - self._last_awb_time > 1.5:
                    self._last_awb_time = current_time
                    
                    # ИСПРАВЛЕНИЕ: Индексы массива физически соответствуют RGB 
                    # (0-Red, 1-Green, 2-Blue), так как мы инвертировали их ранее для QImage
                    avg_r = float(np.mean(rgb[:, :, 0]))
                    avg_g = float(np.mean(rgb[:, :, 1]))
                    avg_b = float(np.mean(rgb[:, :, 2]))
                    
                    if avg_r > 5 and avg_b > 5:
                        try:
                            nodemap = self.camera.GetNodeMap()
                            ratio_node = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                            selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                            
                            # Вычисляем и применяем Красный канал
                            selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                            current_red = ratio_node.GetValue()
                            target_red = current_red * (avg_g / avg_r)
                            
                            # Вычисляем и применяем Синий канал
                            selector.SetIntValue(selector.GetEntryByName("Blue").GetValue())
                            current_blue = ratio_node.GetValue()
                            target_blue = current_blue * (avg_g / avg_b)
                            
                            # Демпфирование для плавности перехода (50%)
                            new_red = current_red * 0.5 + target_red * 0.5
                            new_blue = current_blue * 0.5 + target_blue * 0.5
                            
                            # Запись в регистры камеры
                            selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                            ratio_node.SetValue(min(ratio_node.GetMax(), max(ratio_node.GetMin(), new_red)))
                            
                            selector.SetIntValue(selector.GetEntryByName("Blue").GetValue())
                            ratio_node.SetValue(min(ratio_node.GetMax(), max(ratio_node.GetMin(), new_blue)))
                            
                            # Отправляем обновленное значение красного канала в UI для ползунка
                            self.wb_red_calculated.emit(new_red)
                        except Exception as e:
                            pass

            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            return img.copy()
        except Exception as e:
            return QImage()

    def set_pixel_format(self, format_name, force_restart=True):
        if not self.camera: return
        with QMutexLocker(self._lock):
            try:
                was_streaming = self.camera.IsStreaming()
                if was_streaming and force_restart:
                    self.camera.EndAcquisition()
                
                nodemap = self.camera.GetNodeMap()
                node_pf = PySpin.CEnumerationPtr(nodemap.GetNode("PixelFormat"))
                if PySpin.IsAvailable(node_pf) and PySpin.IsWritable(node_pf):
                    entry = node_pf.GetEntryByName(format_name)
                    if PySpin.IsAvailable(entry):
                        node_pf.SetIntValue(entry.GetValue())
                        self.pixel_format_str = format_name
                
                if was_streaming and force_restart:
                    self.camera.BeginAcquisition()
            except: pass
    
    def set_gamma(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                gamma_enable = PySpin.CBooleanPtr(nodemap.GetNode("GammaEnable"))
                if PySpin.IsAvailable(gamma_enable) and PySpin.IsWritable(gamma_enable):
                    gamma_enable.SetValue(True)
                
                node = PySpin.CFloatPtr(nodemap.GetNode("Gamma"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(max(node.GetMin(), min(value, node.GetMax())))
            except: pass

    def set_gain(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gain"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
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
                    node.SetValue(max(node.GetMin(), min(value, node.GetMax())))
            except: pass

    def set_wb_red(self, value):
        if self.camera and not self.wb_auto:
            try:
                nodemap = self.camera.GetNodeMap()
                selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                if PySpin.IsAvailable(selector) and PySpin.IsWritable(selector):
                    selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                
                ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                if PySpin.IsAvailable(ratio) and PySpin.IsWritable(ratio):
                    ratio.SetValue(value)
            except: pass

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
    """UI Controller: Связывает QML интерфейс с CameraWorker."""
    frameChanged = Signal()
    statusChanged = Signal()
    imagePathChanged = Signal()
    currentFpsChanged = Signal()
    averageFpsChanged = Signal()
    targetFpsChanged = Signal()
    efficiencyChanged = Signal()
    resolutionChanged = Signal()
    gainChanged = Signal()
    exposureChanged = Signal()
    wbRedChanged = Signal()
    wbAutoChanged = Signal()
    pixelFormatChanged = Signal()
    gammaChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "Готов"
        self._image_path = ""
        self._currentFps = 0.0
        self._averageFps = 0.0
        self._targetFps = 0.0
        self._efficiency = 0.0
        self._resolution = "Неизвестно"
        
        self.FORMAT_MAP = {0: "Mono8", 1: "RGB8", 2: "BayerRG8"}
        
        self.DEFAULT_CONFIG = {
            "exposure": 20000.0,
            "gain": 10.0,
            "wb_red": 1.20,
            "gamma": 1.0,
            "wb_auto": True, # АВТО включено по умолчанию
            "pixel_format_idx": 2 
        }
        
        self.CONFIG_FILE = os.path.join(os.path.dirname(__file__), "camera_preset.json")
        self._gain_value = self.DEFAULT_CONFIG["gain"]
        self._wb_red_value = self.DEFAULT_CONFIG["wb_red"]
        self._wb_auto = self.DEFAULT_CONFIG["wb_auto"]
        self._gamma_value = self.DEFAULT_CONFIG["gamma"]
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
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        self.worker.gamma = self._gamma_value
        self.worker.wb_auto = self._wb_auto
        self.worker.pixel_format_str = self.FORMAT_MAP.get(self._pixel_format_index, "BayerRG8")
        
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.status_changed.connect(self._update_status)
        self.worker.metrics_updated.connect(self._on_metrics_updated)
        self.worker.resolution_updated.connect(self._on_resolution_updated)
        self.worker.wb_red_calculated.connect(self._on_wb_red_calculated) # Подключаем новый сигнал
        self.worker.start()

    @Slot()
    def stop_camera(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._update_status("Остановлено")
            self._on_metrics_updated(0.0, 0.0, 0.0, 0.0)

    def _on_frame_ready(self, qimage):
        if self.provider:
            self.provider.update_image(qimage)
            self._image_path = f"image://live/frame_{time.time()}"
            self.imagePathChanged.emit()

    def _update_status(self, msg):
        self._status = msg
        self.statusChanged.emit()

    def _on_metrics_updated(self, cur, avg, tgt, eff):
        self._currentFps = cur
        self._averageFps = avg
        self._targetFps = tgt
        self._efficiency = eff
        self.currentFpsChanged.emit()
        self.averageFpsChanged.emit()
        self.targetFpsChanged.emit()
        self.efficiencyChanged.emit()

    def _on_resolution_updated(self, res):
        self._resolution = res
        self.resolutionChanged.emit()
        
    def _on_wb_red_calculated(self, val):
        """Слот: обновляет UI при авторасчете баланса белого"""
        self._wb_red_value = val
        self.wbRedChanged.emit()

    @Property(str, notify=statusChanged)
    def status(self): return self._status
    @Property(float, notify=currentFpsChanged)
    def currentFps(self): return self._currentFps
    @Property(float, notify=averageFpsChanged)
    def averageFps(self): return self._averageFps
    @Property(float, notify=targetFpsChanged)
    def targetFps(self): return self._targetFps
    @Property(float, notify=efficiencyChanged)
    def efficiency(self): return self._efficiency
    @Property(str, notify=resolutionChanged)
    def resolution(self): return self._resolution

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
            if self.worker and not self._wb_auto: 
                self.worker.set_wb_red(val)
            self.wbRedChanged.emit()
    
    @Property(float, notify=gammaChanged)
    def gammaValue(self): return self._gamma_value
    @gammaValue.setter
    def gammaValue(self, val):
        if self._gamma_value != val:
            self._gamma_value = val
            if self.worker: self.worker.set_gamma(val)
            self.gammaChanged.emit()

    @Property(float, notify=exposureChanged)
    def exposureValue(self): return self._exposure_value
    @exposureValue.setter
    def exposureValue(self, val):
        if self._exposure_value != val:
            self._exposure_value = val
            if self.worker: self.worker.set_exposure(val)
            self.exposureChanged.emit()

    @Property(bool, notify=wbAutoChanged)
    def wbAuto(self): return self._wb_auto
    @wbAuto.setter
    def wbAuto(self, val):
        if self._wb_auto != val:
            self._wb_auto = val
            if self.worker: 
                self.worker.wb_auto = val
                # При отключении авто - фиксируем последнее вычисленное значение в железо
                if not val:
                    self.worker.set_wb_red(self._wb_red_value)
            self.wbAutoChanged.emit()

    @Property(int, notify=pixelFormatChanged)
    def pixelFormatIndex(self): return self._pixel_format_index
    @pixelFormatIndex.setter
    def pixelFormatIndex(self, val):
        if self._pixel_format_index != val:
            self._pixel_format_index = val
            if self.worker: self.worker.set_pixel_format(self.FORMAT_MAP.get(val, "Mono8"))
            self.pixelFormatChanged.emit()

    @Slot()
    def reset_defaults(self):
        self.exposureValue = self.DEFAULT_CONFIG["exposure"]
        self.gainValue = self.DEFAULT_CONFIG["gain"]
        self.wbRedValue = self.DEFAULT_CONFIG["wb_red"]
        self.wbAuto = self.DEFAULT_CONFIG["wb_auto"]
        self.pixelFormatIndex = self.DEFAULT_CONFIG["pixel_format_idx"]
        self.gammaValue = self.DEFAULT_CONFIG["gamma"]
        self._update_status("Сброс настроек")

    @Slot()
    def save_preset(self):
        config = {
            "exposure": self._exposure_value, "gain": self._gain_value,
            "wb_red": self._wb_red_value, "pixel_format_idx": self._pixel_format_index,
            "wb_auto": self._wb_auto, "gamma": self._gamma_value
        }
        try:
            with open(self.CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
            self._update_status("Пресет сохранен")
        except: pass

    @Slot()
    def load_preset(self):
        if not os.path.exists(self.CONFIG_FILE): return
        try:
            with open(self.CONFIG_FILE, 'r') as f: config = json.load(f)
            self.exposureValue = config.get("exposure", self._exposure_value)
            self.gainValue = config.get("gain", self._gain_value)
            self.wbRedValue = config.get("wb_red", self._wb_red_value)
            self.pixelFormatIndex = config.get("pixel_format_idx", self._pixel_format_index)
            self.wbAuto = config.get("wb_auto", True)
            self.gammaValue = config.get("gamma", self._gamma_value)
            self._update_status("Пресет загружен")
        except: pass

    @Slot(str, str, int)
    def capture_photo(self, file_url, fmt, q):
        # Безопасная кроссплатформенная конвертация URL в системный путь
        path = QUrl(file_url).toLocalFile()
        if not path:
            path = file_url.replace("file:///", "").replace("file://", "")

        if self.provider:
            # Блокируем мьютекс только на время копирования кадра в память,
            # чтобы не задерживать видеопоток (Zero-Copy защита)
            with QMutexLocker(self.provider.mutex):
                img = self.provider._current_image.copy()
            
            if not img.isNull():
                success = img.save(path, fmt.upper(), q)
                if success:
                    logger.info(f"Снимок сохранен: {path}")
                    self._update_status("Снимок сохранен")
                else:
                    logger.error(f"Ошибка записи: {path}")
                    self._update_status("Ошибка сохранения")
            else:
                self._update_status("Нет кадра")