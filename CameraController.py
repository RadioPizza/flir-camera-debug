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
        self.exposure_time = 20000 
        self.gain = 15.0
        # [НОВОЕ] Баланс белого (Ratio для красного канала)
        self.wb_red = 1.33 
        
        self.packet_size = 9000
        self.packet_delay = 2000

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
            
            # 1. Packet Size
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                packet_size_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_size_node) and PySpin.IsWritable(packet_size_node):
                    packet_size_node.SetValue(min(packet_size_node.GetMax(), self.packet_size))
            except: pass

            # 2. Buffer Handling
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                buffer_mode = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(buffer_mode) and PySpin.IsWritable(buffer_mode):
                    entry = buffer_mode.GetEntryByName("NewestOnly")
                    if PySpin.IsAvailable(entry):
                        buffer_mode.SetIntValue(entry.GetValue())
            except: pass

            # 3. Exposure (Fixed 20ms)
            try:
                exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exposure_auto) and PySpin.IsWritable(exposure_auto):
                    exposure_auto.SetIntValue(exposure_auto.GetEntryByName("Off").GetValue())
                
                exposure_time = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(exposure_time) and PySpin.IsWritable(exposure_time):
                    exposure_time.SetValue(20000.0)
            except: pass

            # 4. Gain
            self.set_gain(self.gain)

            # 5. [НОВОЕ] White Balance Init
            # Если мы хотим управлять вручную, нужно выключить Auto
            self.set_wb_red(self.wb_red)
            
        except Exception as e:
            logger.error(f"Ошибка настройки камеры: {e}")

    def _convert_to_qimage(self, image_result):
        try:
            image_data = image_result.GetNDArray()
            pixel_format = image_result.GetPixelFormat()
            rgb = None

            # Конвертация в BGR (для OpenCV)
            if pixel_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerRG8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerBG8:
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
                if len(image_data.shape) == 2:
                    rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
                else:
                    return QImage()

            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            
            # Format_RGB888 инвертирует каналы BGR -> RGB, исправляя цвета
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            return img.copy() 
            
        except Exception as e:
            logger.error(f"Ошибка конвертации: {e}")
            return QImage()

    def set_gain(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gain"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
            except: pass

    # [НОВОЕ] Логика установки баланса белого
    def set_wb_red(self, value):
        if self.camera:
            try:
                nodemap = self.camera.GetNodeMap()
                
                # 1. Выключаем авто-баланс, чтобы ручное управление работало
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())

                # 2. Выбираем селектор "Red"
                selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                if PySpin.IsAvailable(selector) and PySpin.IsWritable(selector):
                    selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                
                # 3. Устанавливаем значение
                ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                if PySpin.IsAvailable(ratio) and PySpin.IsWritable(ratio):
                    ratio.SetValue(value)
                    self.wb_red = value
                    logger.info(f"WB Red Ratio set to: {value}")
            except Exception as e:
                logger.error(f"Ошибка WB: {e}")
            
    def capture_photo(self, file_path, format, quality):
        # ... (код сохранения фото можно взять из прошлого примера)
        pass

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
        self._wb_red_value = 1.5 # Дефолтное значение красного канала
        
        self.worker = None
        self.provider = None

    def set_image_provider(self, provider):
        self.provider = provider

    @Property(str, notify=imagePathChanged)
    def imagePath(self):
        return self._image_path

    @Slot()
    def start_camera(self):
        if self.worker and self.worker.isRunning(): return
        self.worker = CameraWorker()
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
    
    # Gain Property
    @Property(float)
    def gainValue(self): return self._gain_value
    @gainValue.setter
    def gainValue(self, val):
        self._gain_value = val
        if self.worker: self.worker.set_gain(val)

    # [НОВОЕ] WB Red Property (вместо Gamma)
    @Property(float)
    def wbRedValue(self): return self._wb_red_value
    @wbRedValue.setter
    def wbRedValue(self, val):
        self._wb_red_value = val
        if self.worker: self.worker.set_wb_red(val)
        
    @Slot(str, str, int)
    def capture_photo(self, path, fmt, q):
        if self.worker:
            self.worker.capture_photo(path, fmt, q)