import os
import time
import logging
import platform
import numpy as np
import cv2
import PySpin

from PySide6.QtCore import QObject, Signal, Property, QThread, Slot, QMutex, QMutexLocker, Qt, QSize
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickImageProvider

# Настройка логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FLIR_System")

class LiveImageProvider(QQuickImageProvider):
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
        
        # Настройки по умолчанию
        self.target_fps = 30
        self.exposure_time = 20000.0 # [ВАЖНО] Исходное значение 20000
        self.gain = 15.0
        self.wb_red = 1.5 
        
        self.packet_size = 9000

    def run(self):
        try:
            logger.info("Инициализация FLIR System...")
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
                        
                except Exception as e:
                    logger.warning(f"Ошибка в цикле захвата: {e}")
                    continue

        except Exception as e:
            logger.error(f"Критическая ошибка Worker: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    def _setup_camera(self):
        """Применение настроек камеры"""
        try:
            nodemap = self.camera.GetNodeMap()
            
            # Packet Size & Buffer (Оптимизация)
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                packet_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_node) and PySpin.IsWritable(packet_node):
                    packet_node.SetValue(min(packet_node.GetMax(), self.packet_size))
                
                buffer_mode = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(buffer_mode) and PySpin.IsWritable(buffer_mode):
                    buffer_mode.SetIntValue(buffer_mode.GetEntryByName("NewestOnly").GetValue())
            except: pass

            # Применяем стартовые значения
            self.set_exposure(self.exposure_time) # Выдержка
            self.set_gain(self.gain)              # Усиление
            self.set_wb_red(self.wb_red)          # Баланс белого
            
        except Exception as e:
            logger.error(f"Ошибка настройки камеры: {e}")

    def _convert_to_qimage(self, image_result):
        # (Код конвертации без изменений, сокращен для краткости)
        try:
            image_data = image_result.GetNDArray()
            pixel_format = image_result.GetPixelFormat()
            rgb = None
            
            if pixel_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerRG8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerBG8: # GR
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerBG2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerGB8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerGB2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerGR8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerGR2BGR)
            elif pixel_format == PySpin.PixelFormat_RGB8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_RGB2BGR)
            elif pixel_format == PySpin.PixelFormat_BGR8:
                rgb = image_data
            else:
                if len(image_data.shape) == 2: rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
                else: return QImage()

            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            return img.copy() 
        except: return QImage()

    # --- СЕТТЕРЫ ---

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
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())

                selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                if PySpin.IsAvailable(selector) and PySpin.IsWritable(selector):
                    selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                
                ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                if PySpin.IsAvailable(ratio) and PySpin.IsWritable(ratio):
                    ratio.SetValue(value)
            except: pass

    # [НОВОЕ] Метод установки выдержки
    def set_exposure(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                # 1. Отключаем авто-экспозицию
                exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exposure_auto) and PySpin.IsWritable(exposure_auto):
                    exposure_auto.SetIntValue(exposure_auto.GetEntryByName("Off").GetValue())
                
                # 2. Ставим время (проверяем границы)
                exposure_time = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(exposure_time) and PySpin.IsWritable(exposure_time):
                    val = max(exposure_time.GetMin(), min(value, exposure_time.GetMax()))
                    exposure_time.SetValue(val)
                    self.exposure_time = val
                    logger.info(f"Exposure set to: {val}")
            except Exception as e:
                logger.error(f"Ошибка Exposure: {e}")

    def capture_photo(self, file_path, format, quality):
        pass # (Логика сохранения)

    def _cleanup(self):
        try:
            if self.camera:
                self.camera.EndAcquisition()
                self.camera.DeInit()
                del self.camera
            if self.system:
                self.system.ReleaseInstance()
        except: pass
    
    def stop(self):
        self.running = False
        self.wait()

class CameraController(QObject):
    frameChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()
    currentFpsChanged = Signal()
    imagePathChanged = Signal() 

    def __init__(self):
        super().__init__()
        self._status = "Готов"
        self._currentFps = 0.0
        self._camera_info = {}
        self._image_path = ""
        self._gain_value = 15.0
        self._wb_red_value = 1.5
        self._exposure_value = 20000.0 # [НОВОЕ] Дефолт
        
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
        # Передаем текущие значения в воркер перед стартом
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        
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

    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property(float, notify=currentFpsChanged)
    def currentFps(self): return self._currentFps

    @Property('QVariantMap', notify=infoChanged)
    def cameraInfo(self): return self._camera_info
    
    # --- Свойства управления ---

    @Property(float)
    def gainValue(self): return self._gain_value
    @gainValue.setter
    def gainValue(self, val):
        self._gain_value = val
        if self.worker: self.worker.set_gain(val)

    @Property(float)
    def wbRedValue(self): return self._wb_red_value
    @wbRedValue.setter
    def wbRedValue(self, val):
        self._wb_red_value = val
        if self.worker: self.worker.set_wb_red(val)

    # [НОВОЕ] Свойство Exposure
    @Property(float)
    def exposureValue(self): return self._exposure_value
    @exposureValue.setter
    def exposureValue(self, val):
        self._exposure_value = val
        if self.worker: self.worker.set_exposure(val)

    @Slot(str, str, int)
    def capture_photo(self, path, fmt, q):
        if self.worker:
            self.worker.capture_photo(path, fmt, q)