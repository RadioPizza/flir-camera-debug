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