# -*- coding: utf-8 -*-

"""
Camera Controller Module.

Обеспечивает взаимодействие с FLIR камерой через PySpin SDK,
обработку изображений и интеграцию с QML через сигналы/слоты.
"""

import os
import time
import logging
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
    """
    Настройка логгера с ротацией файлов и форматированием.
    
    Returns:
        logging.Logger: Настроенный объект логгера.
    """
    logger = logging.getLogger("FLIR_System")
    logger.setLevel(logging.DEBUG)  # Ловим всё

    # Формат: Время - Уровень - [Файл:Строка] - Сообщение
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    # 1. Вывод в консоль (Только важное)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 2. Вывод в файл (Всё подряд, макс 5 МБ, храним 3 файла)
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

    # Очищаем старые хендлеры
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


# Инициализируем глобальный логгер
logger = setup_logger()


class LiveImageProvider(QQuickImageProvider):
    """
    Провайдер изображений для QML (Direct Memory Access).
    Позволяет передавать QImage в QML без кодирования в Base64.
    """
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._current_image = QImage(800, 600, QImage.Format_RGB888)
        self._current_image.fill(QColor("black"))
        self.mutex = QMutex()

    def requestImage(self, id, size, requestedSize):
        """Вызывается движком QML при запросе кадра."""
        with QMutexLocker(self.mutex):
            return self._current_image
            
    def update_image(self, image):
        """Обновляет буфер изображения в потокобезопасном режиме."""
        with QMutexLocker(self.mutex):
            if not image.isNull():
                self._current_image = image


class CameraWorker(QThread):
    """
    Рабочий поток захвата видео (Backend).
    Управляет циклом получения кадров от PySpin SDK.
    """
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
        
        logger.debug("CameraWorker инициализирован с параметрами по умолчанию.")

    def run(self):
        """Основной цикл потока."""
        try:
            logger.info("=== НАЧАЛО СЕССИИ ЗАХВАТА ===")
            logger.info(f"System: {platform.system()} {platform.release()}")

            self.system = PySpin.System.GetInstance()
            
            # Поиск камер
            cam_list = self.system.GetCameras()
            count = cam_list.GetSize()
            logger.info(f"Обнаружено камер: {count}")
            
            if count == 0:
                msg = "Камеры не найдены"
                logger.error(msg)
                self.error_occurred.emit(msg)
                cam_list.Clear()
                self.system.ReleaseInstance()
                return

            self.camera = cam_list.GetByIndex(0)
            self.camera.Init()
            
            # Логируем модель
            try:
                nodemap = self.camera.GetTLDeviceNodeMap()
                model = PySpin.CStringPtr(nodemap.GetNode("DeviceModelName")).GetValue()
                serial = PySpin.CStringPtr(nodemap.GetNode("DeviceSerialNumber")).GetValue()
                logger.info(f"Подключено к: {model} (S/N: {serial})")
            except:
                logger.warning("Не удалось прочитать модель камеры")

            self._setup_camera()
            
            self.camera.BeginAcquisition()
            logger.info("Acquisition Started")
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            fps_counter = 0
            fps_timer = time.time()
            
            while self.running:
                try:
                    # Таймаут 2000 мс
                    image_result = self.camera.GetNextImage(2000)
                    
                    if image_result.IsIncomplete():
                        status = image_result.GetImageStatus()
                        logger.warning(f"Image Incomplete. Status: {status}")
                        image_result.Release()
                        continue

                    qimage = self._convert_to_qimage(image_result)
                    
                    if not qimage.isNull():
                        self.frame_ready.emit(qimage)
                        fps_counter += 1
                    
                    image_result.Release()
                    
                    # Расчет FPS
                    current_time = time.time()
                    if current_time - fps_timer >= 1.0:
                        fps = fps_counter / (current_time - fps_timer)
                        self.fps_updated.emit(fps)
                        
                        if fps < 10.0:
                            logger.warning(f"Low FPS detected: {fps:.2f}")
                        
                        fps_counter = 0
                        fps_timer = current_time
                        
                except PySpin.SpinnakerException as ex:
                    logger.error(f"Spinnaker Exception: {ex}")
                    continue
                except Exception as e:
                    logger.exception(f"Unexpected error in loop: {e}")
                    continue

        except Exception as e:
            logger.critical(f"Critical Worker Crash: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()
            logger.info("=== КОНЕЦ СЕССИИ ЗАХВАТА ===")

    def _setup_camera(self):
        """Применение настроек камеры и оптимизация потока."""
        logger.info("Применение начальных настроек камеры...")
        try:
            # Настройка пакетов (Jumbo Frames) и буферизации
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                packet_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_node) and PySpin.IsWritable(packet_node):
                    val = min(packet_node.GetMax(), self.packet_size)
                    packet_node.SetValue(val)
                    logger.debug(f"Packet size set to: {val}")
                
                buffer_mode = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(buffer_mode) and PySpin.IsWritable(buffer_mode):
                    buffer_mode.SetIntValue(buffer_mode.GetEntryByName("NewestOnly").GetValue())
                    logger.debug("Buffer mode: NewestOnly")
            except Exception as e: 
                logger.warning(f"Stream config error: {e}")

            # Применяем значения сенсоров
            self.set_exposure(self.exposure_time)
            self.set_gain(self.gain)
            self.set_wb_red(self.wb_red)
            
            logger.info("Настройки применены успешно.")
            
        except Exception as e:
            logger.error(f"Ошибка настройки камеры: {e}", exc_info=True)

    def _convert_to_qimage(self, image_result):
        """Конвертация PySpin Image -> QImage (Format_RGB888)."""
        try:
            image_data = image_result.GetNDArray()
            pixel_format = image_result.GetPixelFormat()
            rgb = None
            
            # Конвертация BGR/Bayer -> RGB
            if pixel_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
            elif pixel_format == PySpin.PixelFormat_BayerRG8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif pixel_format == PySpin.PixelFormat_RGB8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_RGB2BGR)
            elif pixel_format == PySpin.PixelFormat_BGR8:
                rgb = image_data
            else:
                # Fallback для остальных форматов
                if len(image_data.shape) == 2: 
                    rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
                else: 
                    return QImage()

            h, w, ch = rgb.shape
            # Format_RGB888 исправляет инверсию цветов (Blue <-> Red)
            img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            return img.copy() 
        except Exception as e:
            logger.error(f"Image conversion error: {e}")
            return QImage()

    # --- СЕТТЕРЫ (Hardware Control) ---

    def set_gain(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gain"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
                    logger.info(f"Gain changed to: {value:.1f} dB")
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
                    logger.info(f"WB Red Ratio changed to: {value:.2f}")
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
                    logger.info(f"Exposure changed to: {val:.1f} us")
            except Exception as e:
                logger.error(f"Failed to set Exposure: {e}")

    def capture_photo(self, file_path, format, quality):
        """Сохранение кадра (Заглушка для реализации)."""
        try:
            logger.info(f"Saving photo to: {file_path}")
            pass 
        except Exception as e:
             logger.error(f"Photo save error: {e}")

    def _cleanup(self):
        """Освобождение ресурсов камеры."""
        try:
            logger.info("Cleaning up resources...")
            if self.camera:
                self.camera.EndAcquisition()
                self.camera.DeInit()
                del self.camera
            if self.system:
                self.system.ReleaseInstance()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    def stop(self):
        self.running = False
        self.wait()


class CameraController(QObject):
    """
    Контроллер приложения (UI Logic).
    Связывает QML интерфейс с рабочим потоком CameraWorker.
    """
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
        
        # Начальные значения свойств
        self._gain_value = 15.0
        self._wb_red_value = 1.5
        self._exposure_value = 20000.0
        
        self.worker = None
        self.provider = None
        
        logger.debug("CameraController initialized")

    def set_image_provider(self, provider):
        self.provider = provider

    @Property(str, notify=imagePathChanged)
    def imagePath(self): return self._image_path

    @Slot()
    def start_camera(self):
        """Запуск потока камеры."""
        logger.info("UI: Start requested")
        if self.worker and self.worker.isRunning(): return
        
        self.worker = CameraWorker()
        
        # Передаем текущие параметры UI в воркер
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.status_changed.connect(self._update_status)
        self.worker.fps_updated.connect(self._update_fps)
        self.worker.start()

    @Slot()
    def stop_camera(self):
        """Остановка потока камеры."""
        logger.info("UI: Stop requested")
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._update_status("Остановлено")

    def _on_frame_ready(self, qimage):
        """Обработка готового кадра из воркера."""
        if self.provider:
            self.provider.update_image(qimage)
            # Трюк с timestamp для обновления Image в QML
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