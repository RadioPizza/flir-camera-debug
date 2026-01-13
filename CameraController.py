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
    """
    Провайдер изображений для QML.
    """
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        # Создаем черную заглушку 800x600
        self._current_image = QImage(800, 600, QImage.Format_RGB888)
        self._current_image.fill(QColor("black"))
        self.mutex = QMutex()

    def requestImage(self, id, size, requestedSize):
        """Метод вызывается движком QML при отрисовке кадра"""
        with QMutexLocker(self.mutex):
            # [ИСПРАВЛЕНИЕ] Возвращаем ТОЛЬКО image, без размера!
            # print(f"DEBUG: QML запросил кадр {id}") # Раскомментируй для отладки
            return self._current_image
            
    def update_image(self, image):
        """Обновление текущего кадра из CameraController"""
        with QMutexLocker(self.mutex):
            if not image.isNull():
                self._current_image = image

class CameraWorker(QThread):
    """Поток захвата: получает кадры и отдает их как QImage"""
    frame_ready = Signal(QImage) # Передаем чистый QImage
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
        self.gamma = 0.7
        self.gamma_enable = True
        
        # Оптимизация GigE
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
            
            logger.info("Начало захвата кадров")

            while self.running:
                try:
                    # Таймаут 2000мс для надежности
                    image_result = self.camera.GetNextImage(2000)
                    
                    if image_result.IsIncomplete():
                        image_result.Release()
                        continue

                    # Конвертация в QImage (быстрая)
                    qimage = self._convert_to_qimage(image_result)
                    
                    if not qimage.isNull():
                        # Отправляем кадр контроллеру
                        self.frame_ready.emit(qimage)
                        fps_counter += 1
                    
                    image_result.Release()
                    
                    # Расчет FPS
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
        """Применение настроек камеры: Выдержка и Баланс белого"""
        try:
            nodemap = self.camera.GetNodeMap()
            
            # 1. Настройка пакетов (Jumbo Frames)
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                packet_size_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_size_node) and PySpin.IsWritable(packet_size_node):
                    packet_size_node.SetValue(min(packet_size_node.GetMax(), self.packet_size))
            except: pass

            # 2. Буферизация (NewestOnly)
            try:
                tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
                buffer_mode = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(buffer_mode) and PySpin.IsWritable(buffer_mode):
                    entry = buffer_mode.GetEntryByName("NewestOnly")
                    if PySpin.IsAvailable(entry):
                        buffer_mode.SetIntValue(entry.GetValue())
            except: pass

            # 3. [НОВОЕ] Выдержка (Exposure) -> 20000 мкс
            logger.info("Настройка выдержки на 20000 мкс...")
            try:
                # Сначала ВЫКЛЮЧАЕМ автоэкспозицию, иначе вручную время не выставить
                exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exposure_auto) and PySpin.IsWritable(exposure_auto):
                    exposure_auto.SetIntValue(exposure_auto.GetEntryByName("Off").GetValue())
                
                # Теперь ставим время
                exposure_time = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(exposure_time) and PySpin.IsWritable(exposure_time):
                    # Проверяем границы, чтобы не сломать камеру
                    target_exposure = 20000.0
                    target_exposure = max(exposure_time.GetMin(), min(target_exposure, exposure_time.GetMax()))
                    exposure_time.SetValue(target_exposure)
                    self.exposure_time = target_exposure # Обновляем переменную в классе
                    logger.info(f"Выдержка установлена: {target_exposure}")
            except Exception as e:
                logger.warning(f"Не удалось настроить выдержку: {e}")

            # 4. [НОВОЕ] Баланс белого (White Balance) -> Auto Continuous
            logger.info("Включение авто-баланса белого...")
            try:
                balance_white_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(balance_white_auto) and PySpin.IsWritable(balance_white_auto):
                    balance_white_auto.SetIntValue(balance_white_auto.GetEntryByName("Continuous").GetValue())
                    logger.info("Авто-баланс белого активирован (Continuous)")
                else:
                    logger.warning("Авто-баланс белого недоступен на этой камере")
            except Exception as e:
                logger.warning(f"Ошибка настройки баланса белого: {e}")

            # 5. Gain & Gamma (Применяем сохраненные значения)
            self.set_gain(self.gain)
            self.set_gamma(self.gamma)
            
        except Exception as e:
            logger.error(f"Критическая ошибка настройки камеры: {e}")

    def _convert_to_qimage(self, image_result):
        """Быстрая конвертация Spinnaker Image -> QImage"""
        try:
            # Получаем numpy массив (это быстро, без копирования)
            image_data = image_result.GetNDArray()
            
            pixel_format = image_result.GetPixelFormat()
            rgb = None

            # --- БЛОК КОНВЕРТАЦИИ ---
            # Оставляем конвертацию в BGR (стандарт OpenCV), 
            # но изменим способ, которым Qt читает эти байты.
            
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

            # --- СОЗДАНИЕ QIMAGE ---
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            
            # [ИСПРАВЛЕНИЕ]
            # Меняем BGR888 на RGB888. 
            # Это заставит Qt прочитать Синий канал как Красный и наоборот.
            # Если сейчас стул синий, а должен быть желтым — это исправит цвета.
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

    def set_gamma(self, value):
        if self.camera:
            try:
                node = PySpin.CFloatPtr(self.camera.GetNodeMap().GetNode("Gamma"))
                if PySpin.IsAvailable(node) and PySpin.IsWritable(node):
                    node.SetValue(value)
            except: pass
            
    def capture_photo(self, file_path, format, quality):
        # Реализуем захват через сохранение последнего кадра
        return False # (Упрощено для примера, логику можно взять из прошлого кода)

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
    """
    Контроллер для QML. 
    Управляет потоком и обновляет ImageProvider.
    """
    frameChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()
    currentFpsChanged = Signal()
    imagePathChanged = Signal() # Сигнал обновления картинки

    def __init__(self):
        super().__init__()
        self._status = "Готов"
        self._currentFps = 0.0
        self._camera_info = {}
        self._image_path = "" # Строка-триггер для QML
        
        self.worker = None
        self.provider = None # Ссылка на провайдер

    def set_image_provider(self, provider):
        """Получаем ссылку на провайдер из main.py"""
        self.provider = provider

    @Property(str, notify=imagePathChanged)
    def imagePath(self):
        """Возвращает URL для Image в QML с уникальным ID для обновления"""
        return self._image_path

    @Slot()
    def start_camera(self):
        if self.worker and self.worker.isRunning():
            return
            
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
        """Главный метод обновления кадра"""
        if self.provider:
            # 1. Загружаем картинку в провайдер (C++ память)
            self.provider.update_image(qimage)
            
            # 2. Обновляем строку URL, чтобы QML понял, что кадр новый
            # Используем time.time() как уникальный ключ
            self._image_path = f"image://live/frame_{time.time()}"
            self.imagePathChanged.emit()

    def _update_status(self, msg):
        self._status = msg
        self.statusChanged.emit()

    def _update_fps(self, fps):
        self._currentFps = fps
        self.currentFpsChanged.emit()

    # Свойства для UI
    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property(float, notify=currentFpsChanged)
    def currentFps(self): return self._currentFps

    @Property('QVariantMap', notify=infoChanged)
    def cameraInfo(self): return self._camera_info
    
    # Сеттеры (Gain/Gamma/Capture) оставлены краткими, добавь их при необходимости из прошлого кода
    @Slot(float)
    def set_gain(self, val): 
        if self.worker: self.worker.set_gain(val)
        
    @Slot(str, str, int)
    def capture_photo(self, path, fmt, q):
        return False