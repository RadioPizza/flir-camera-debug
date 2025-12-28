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
    
    def run(self):
        """Основной цикл захвата"""
        try:
            logger.info("Инициализация FLIR...")
            
            self.system = PySpin.System.GetInstance()
            cam_list = self.system.GetCameras()
            
            if cam_list.GetSize() == 0:
                self.error_occurred.emit("Камеры не найдены")
                return

            self.camera = cam_list.GetByIndex(0)
            self.camera.Init()
            
            # Базовая настройка
            self._setup_camera()
            
            self.camera.BeginAcquisition()
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            fps_counter = 0
            fps_timer = time.time()
            
            while self.running:
                try:
                    image_result = self.camera.GetNextImage(1000)
                    
                    if image_result.IsIncomplete():
                        image_result.Release()
                        continue

                    qimage = self._convert_to_qimage(image_result)
                    
                    if not qimage.isNull():
                        with QMutexLocker(self.mutex):
                            self.last_valid_frame = qimage.copy()
                        
                        self.frame_ready.emit(qimage)
                        
                        # data URL для QML
                        data_url = self._convert_to_data_url(qimage)
                        self.frame_data_ready.emit(data_url)
                        
                        fps_counter += 1
                    
                    image_result.Release()
                    
                    # Обновление FPS
                    current_time = time.time()
                    if current_time - fps_timer >= 1.0:
                        fps = fps_counter / (current_time - fps_timer)
                        self.fps_updated.emit(fps)
                        fps_counter = 0
                        fps_timer = current_time
                        
                except Exception as e:
                    logger.warning(f"Ошибка кадра: {e}")
                    continue

        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    def _setup_camera(self):
        """Настройка камеры с оптимизациями для производительности"""
        try:
            nodemap = self.camera.GetNodeMap()
            tl_stream_nodemap = self.camera.GetTLStreamNodeMap()
            
            # ОПТИМИЗАЦИЯ ПОТОКА ДАННЫХ (GigE параметры)
            try:
                # 1. Настройка размера пакета (Packet Size) - КЛЮЧЕВАЯ НАСТРОЙКА
                packet_size_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("StreamPacketSize"))
                if PySpin.IsAvailable(packet_size_node) and PySpin.IsWritable(packet_size_node):
                    # Проверяем доступный диапазон
                    packet_size_min = packet_size_node.GetMin()
                    packet_size_max = packet_size_node.GetMax()
                    
                    # Устанавливаем 9000 если поддерживается, иначе максимальный
                    if packet_size_max >= self.packet_size:
                        packet_size_node.SetValue(self.packet_size)
                        logger.info(f"Размер пакета установлен: {self.packet_size} байт (jumbo frames)")
                    else:
                        packet_size_node.SetValue(packet_size_max)
                        self.packet_size = packet_size_max
                        logger.info(f"Размер пакета установлен на максимальный: {packet_size_max} байт")
                        
                    # Обновляем информацию
                    self.info_updated.emit("packet_size", f"{self.packet_size} байт")
                else:
                    logger.warning("Узел размера пакета недоступен")
                    
            except Exception as e:
                logger.warning(f"Не удалось настроить размер пакета: {e}")
            
            try:
                # 2. Отключаем авто-настройку размера пакета (для стабильности)
                auto_packet_size_node = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamAutoNegotiatePacketSize"))
                if PySpin.IsAvailable(auto_packet_size_node) and PySpin.IsWritable(auto_packet_size_node):
                    if not self.auto_packet_size:
                        entry = auto_packet_size_node.GetEntryByName("Off")
                    else:
                        entry = auto_packet_size_node.GetEntryByName("On")
                        
                    if PySpin.IsAvailable(entry):
                        auto_packet_size_node.SetIntValue(entry.GetValue())
                        logger.info(f"Авто-настройка размера пакета: {'Включена' if self.auto_packet_size else 'Отключена'}")
            except Exception as e:
                logger.warning(f"Не удалось настроить авто-настройку пакета: {e}")
            
            try:
                # 3. Настройка задержки между пакетами (Packet Delay) - минимизируем
                packet_delay_node = PySpin.CIntegerPtr(tl_stream_nodemap.GetNode("GevSCPD"))
                if PySpin.IsAvailable(packet_delay_node) and PySpin.IsWritable(packet_delay_node):
                    packet_delay_node.SetValue(self.packet_delay)
                    logger.info(f"Задержка между пакетами: {self.packet_delay} нс")
            except Exception as e:
                logger.warning(f"Не удалось настроить задержку пакетов: {e}")
            
            try:
                # 4. Настройка режима передачи (максимальная производительность)
                stream_buffer_handling_mode_node = PySpin.CEnumerationPtr(tl_stream_nodemap.GetNode("StreamBufferHandlingMode"))
                if PySpin.IsAvailable(stream_buffer_handling_mode_node) and PySpin.IsWritable(stream_buffer_handling_mode_node):
                    entry = stream_buffer_handling_mode_node.GetEntryByName("NewestOnly")
                    if PySpin.IsAvailable(entry):
                        stream_buffer_handling_mode_node.SetIntValue(entry.GetValue())
                        logger.info("Режим буфера: NewestOnly (только новые кадры)")
            except Exception as e:
                logger.warning(f"Не удалось настроить режим буфера: {e}")
            
            # БАЗОВЫЕ НАСТРОЙКИ КАМЕРЫ
            
            # Разрешение
            width_node = PySpin.CIntegerPtr(nodemap.GetNode("Width"))
            height_node = PySpin.CIntegerPtr(nodemap.GetNode("Height"))
            
            if PySpin.IsAvailable(width_node):
                width_node.SetValue(self.target_width)
            if PySpin.IsAvailable(height_node):
                height_node.SetValue(self.target_height)
            
            self.info_updated.emit("resolution", f"{self.target_width}×{self.target_height}")
            
            # Формат пикселей
            pixel_format = PySpin.CEnumerationPtr(nodemap.GetNode("PixelFormat"))
            if PySpin.IsAvailable(pixel_format):
                # Пробуем монохромный формат для повышения FPS
                formats = ["Mono8", "BayerBG8", "BayerRG8", "BayerGB8", "BayerGR8", "RGB8", "BGR8"]
                for fmt in formats:
                    entry = pixel_format.GetEntryByName(fmt)
                    if PySpin.IsAvailable(entry):
                        pixel_format.SetIntValue(entry.GetValue())
                        logger.info(f"Формат пикселей: {fmt}")
                        self.info_updated.emit("pixel_format", fmt)
                        break
            
            # Частота кадров (пробуем максимум)
            try:
                fps_node = PySpin.CFloatPtr(nodemap.GetNode("AcquisitionFrameRate"))
                if PySpin.IsAvailable(fps_node):
                    # Пробуем установить максимально доступный FPS
                    fps_max = fps_node.GetMax()
                    logger.info(f"Максимальный доступный FPS: {fps_max}")
                    
                    if self.target_fps > fps_max:
                        self.target_fps = fps_max
                    
                    fps_node.SetValue(self.target_fps)
                    logger.info(f"FPS установлен: {self.target_fps}")
            except Exception as e:
                logger.warning(f"Не удалось установить FPS: {e}")
            
            # Автоэкспозиция
            try:
                exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
                if PySpin.IsAvailable(exposure_auto):
                    entry = exposure_auto.GetEntryByName("Off")
                    if PySpin.IsAvailable(entry):
                        exposure_auto.SetIntValue(entry.GetValue())
                        logger.info("Автоэкспозиция: Off")
            except:
                pass
            
            # Экспозиция
            exposure_node = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
            if PySpin.IsAvailable(exposure_node):
                exposure_node.SetValue(self.exposure_time)
                logger.info(f"Экспозиция: {self.exposure_time} мкс")
            
            # Автоусиление
            try:
                gain_auto = PySpin.CEnumerationPtr(nodemap.GetNode("GainAuto"))
                if PySpin.IsAvailable(gain_auto):
                    entry = gain_auto.GetEntryByName("Continuous")
                    if PySpin.IsAvailable(entry):
                        gain_auto.SetIntValue(entry.GetValue())
                        logger.info("Автоусиление: Continuous")
            except:
                pass
            
            # Усиление
            gain_node = PySpin.CFloatPtr(nodemap.GetNode("Gain"))
            if PySpin.IsAvailable(gain_node):
                gain_node.SetValue(self.gain)
                logger.info(f"Gain установлен: {self.gain:.1f} dB")
            
            # Gamma
            try:
                gamma_enable_node = PySpin.CBooleanPtr(nodemap.GetNode("GammaEnable"))
                if PySpin.IsAvailable(gamma_enable_node):
                    gamma_enable_node.SetValue(self.gamma_enable)
                    logger.info(f"Gamma Enable: {'Включено' if self.gamma_enable else 'Выключено'}")
                
                if self.gamma_enable:
                    gamma_node = PySpin.CFloatPtr(nodemap.GetNode("Gamma"))
                    if PySpin.IsAvailable(gamma_node):
                        gamma_node.SetValue(self.gamma)
                        logger.info(f"Gamma установлена: {self.gamma}")
            except Exception as e:
                logger.warning(f"Не удалось настроить Gamma: {e}")
            
        except Exception as e:
            logger.warning(f"Ошибка настройки: {e}")

    def _cleanup(self):
        """Очистка ресурсов"""
        self.running = False
        
        try:
            if self.camera:
                self.camera.EndAcquisition()
                self.camera.DeInit()
                del self.camera
                self.camera = None
            
            if self.system:
                self.system.ReleaseInstance()
                self.system = None
                
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")

    def stop(self):
        """Остановка потока"""
        self.running = False
        if self.isRunning():
            self.wait(2000)
    
    def capture_photo(self, file_path, format="JPEG", quality=95):
        """Сохранение снимка"""
        try:
            with QMutexLocker(self.mutex):
                frame = self.last_valid_frame.copy() if self.last_valid_frame else QImage()
            
            if frame.isNull():
                return False
            
            if not file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                file_path += '.jpg' if format.upper() == 'JPEG' else '.png'
            
            return frame.save(file_path, format, quality)
            
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            return False

    def set_display_fps(self, fps):
        """Установка частоты обновления отображения"""
        if fps > 0:
            self.frame_interval = 1.0 / fps
            logger.info(f"Частота отображения установлена: {fps} FPS")
        
    class CameraController(QObject):
    """Контроллер для QML с оптимизацией отображения"""
    
    # Сигналы
    frameChanged = Signal()
    frameDataChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()
    currentFpsChanged = Signal()
    
    # Сигналы для обновления изображения
    imageUpdated = Signal(QByteArray, int, int)  # Для прямого обновления

    def __init__(self):
        super().__init__()
        self._frame_data = QByteArray()
        self._display_width = 800
        self._display_height = 600
        self._status = "Готов"
        self._currentFps = 0.0
        self._camera_info = {
            "resolution": "1936×1464",
            "pixel_format": "Неизвестно",
            "cameras_found": "0",
            "gain": "10.0 dB",
            "gamma": "1.0",
            "gamma_enabled": "Нет",
            "exposure": "20000 мкс",
            "fps": "30.0",
            "display_fps": "30.0"
        }
        self.worker = None
        
        # Текущие значения параметров
        self._gain_value = 10.0
        self._gamma_value = 1.0
        self._gamma_enabled = False
        self._exposure_value = 20000.0
        self._display_fps = 30.0
        
        # Для отображения
        self._pixmap = QPixmap()
        
        # Таймер для контроля частоты обновления QML
        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._update_display)
        self._display_timer.setInterval(33)  # 30 FPS по умолчанию
        
        # Обновление информации о камерах
        self._update_camera_count()

    def _update_camera_count(self):
        """Подсчет доступных камер"""
        try:
            system = PySpin.System.GetInstance()
            cam_list = system.GetCameras()
            count = cam_list.GetSize()
            self._camera_info["cameras_found"] = str(count)
            cam_list.Clear()
            system.ReleaseInstance()
            self.infoChanged.emit()
        except:
            pass

    @Slot()
    def start_camera(self):
        """Запуск камеры"""
        if self.worker and self.worker.isRunning():
            return
        
        self.worker = CameraWorker()
        self.worker.frame_data_ready.connect(self._on_frame_data_ready)
        self.worker.status_changed.connect(self._on_status_changed)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.info_updated.connect(self._on_info_updated)
        self.worker.fps_updated.connect(self._on_fps_updated)
        self.worker.start()
        
        # Запускаем таймер обновления отображения
        self._display_timer.start()
        
        logger.info("Камера запущена с оптимизацией отображения")

    @Slot()
    def stop_camera(self):
        """Остановка камеры"""
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._status = "Остановлено"
            self.statusChanged.emit()
            self._display_timer.stop()
            
        logger.info("Камера остановлена")

    def _on_frame_data_ready(self, jpeg_data, width, height):
        """Обработка JPEG данных для отображения"""
        try:
            if not jpeg_data.isEmpty():
                self._frame_data = jpeg_data
                self._display_width = width
                self._display_height = height
                self.frameDataChanged.emit()
                
                # Отправляем сигнал с сырыми данными
                self.imageUpdated.emit(jpeg_data, width, height)
        except Exception as e:
            logger.error(f"Ошибка обработки данных: {e}")

    def _on_status_changed(self, status):
        """Обновление статуса"""
        self._status = status
        self.statusChanged.emit()

    def _on_error(self, error):
        """Обработка ошибки"""
        logger.error(f"Ошибка: {error}")
        self._status = f"Ошибка: {error}"
        self.statusChanged.emit()
        self._display_timer.stop()

    def _on_info_updated(self, key, value):
        """Обновление информации"""
        self._camera_info[key] = value
        self.infoChanged.emit()

    def _on_fps_updated(self, fps):
        """Обновление FPS"""
        self._currentFps = fps
        self.currentFpsChanged.emit()

    def _update_display(self):
        """Метод для обновления отображения (вызывается по таймеру)"""
        if not self._frame_data.isEmpty():
            self.frameDataChanged.emit()

    @Slot(str, str, int)
    def capture_photo(self, file_path, format, quality):
        """Снимок"""
        if self.worker and self.worker.isRunning():
            return self.worker.capture_photo(file_path, format, quality)
        return False

    @Slot(float)
    def set_gain(self, gain_value):
        """Установка усиления"""
        logger.info(f"Установка Gain: {gain_value} dB")
        self._gain_value = gain_value
        self._camera_info["gain"] = f"{gain_value:.1f} dB"
        self.infoChanged.emit()
        
        if self.worker and self.worker.isRunning():
            return self.worker.set_gain(gain_value)
        return False

    @Slot(float)
    def set_exposure(self, exposure_value):
        """Установка экспозиции"""
        logger.info(f"Установка экспозиции: {exposure_value} мкс")
        self._exposure_value = exposure_value
        self._camera_info["exposure"] = f"{exposure_value:.0f} мкс"
        self.infoChanged.emit()
        
        if self.worker and self.worker.isRunning():
            return self.worker.set_exposure(exposure_value)
        return False

    @Slot(float)
    def set_gamma(self, gamma_value):
        """Установка значения Gamma"""
        logger.info(f"Установка Gamma: {gamma_value}")
        self._gamma_value = gamma_value
        self._camera_info["gamma"] = str(gamma_value)
        self.infoChanged.emit()
        
        if self.worker and self.worker.isRunning():
            return self.worker.set_gamma(gamma_value)
        return False

    @Slot(bool)
    def set_gamma_enable(self, enabled):
        """Включение/выключение Gamma"""
        logger.info(f"Gamma Enable: {'Включено' if enabled else 'Выключено'}")
        self._gamma_enabled = enabled
        self._camera_info["gamma_enabled"] = "Да" if enabled else "Нет"
        self.infoChanged.emit()
        
        if self.worker and self.worker.isRunning():
            return self.worker.set_gamma_enable(enabled)
        return False

    @Slot(float)
    def set_display_fps(self, fps):
        """Установка частоты обновления отображения"""
        if fps > 0 and fps <= 60:  # Ограничиваем разумными значениями
            self._display_fps = fps
            self._camera_info["display_fps"] = f"{fps:.1f}"
            self.infoChanged.emit()
            
            # Обновляем интервал таймера
            interval = int(1000 / fps)  # мс
            self._display_timer.setInterval(interval)
            
            # Обновляем настройки в worker
            if self.worker and self.worker.isRunning():
                self.worker.set_display_fps(fps)
            
            logger.info(f"Частота отображения изменена: {fps} FPS")
            return True
        return False
    
    