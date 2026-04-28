# -*- coding: utf-8 -*-

"""
Модуль контроллера камеры FLIR Blackfly S.
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


def setup_logger():
    """Настройка системы логирования с ротацией файлов (ограничение размера лога)."""
    logger = logging.getLogger("FLIR_System")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    
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
    """
    Провайдер изображений для QML. 
    Использует QMutex для защиты разделяемой памяти между потоком камеры и потоком GUI.
    """
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._current_image = QImage(800, 600, QImage.Format_RGB888)
        self._current_image.fill(QColor("black"))
        self.mutex = QMutex()

    def requestImage(self, id, size, requestedSize):
        """Вызывается QML-движком при обновлении источника (source)."""
        with QMutexLocker(self.mutex):
            return self._current_image
            
    def update_image(self, image):
        """Вызывается из CameraController для загрузки нового кадра."""
        with QMutexLocker(self.mutex):
            if not image.isNull():
                self._current_image = image


class CameraWorker(QThread):
    """
    Рабочий поток для взаимодействия с SDK Spinnaker (PySpin).
    Инкапсулирует всю логику работы с железом, чтобы не блокировать GUI.
    """
    # Сигналы для общения с контроллером 
    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    metrics_updated = Signal(float, float, float, float)
    resolution_updated = Signal(str)
    wb_red_calculated = Signal(float)

    def __init__(self):
        super().__init__()
        self.camera = None
        self.system = None
        self.running = False
        self._lock = QMutex() 
        
        # Параметры сенсора по умолчанию
        self.exposure_time = 20000.0
        self.gain = 10.0
        self.wb_red = 1.20
        self.gamma = 1.0
        self.wb_auto = False
        self.pixel_format_str = "BayerRG8"
        self.packet_size = 9000
        
        # Параметры подсистемы записи видео
        self._video_lock = QMutex()
        self.is_recording = False
        self.video_writer = None
        self.record_path = ""
        self.record_fps = 30.0

    def run(self):
        """Главный цикл захвата кадров (выполняется в отдельном потоке)."""
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
            
            # Применяем конфигурацию перед стартом потока
            self._apply_initial_settings()
            
            # Считывание эталонных метрик камеры
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
                logger.warning(f"Ошибка чтения метрик сенсора: {e}")

            self.camera.BeginAcquisition()
            self.status_changed.emit("Камера запущена")
            self.running = True
            
            # Счетчики для телеметрии
            fps_counter = 0
            total_frames = 0
            start_time = time.time()
            fps_timer = start_time
            
            while self.running:
                with QMutexLocker(self._lock):
                    if not self.running: break
                    try:
                        # Получение сырого кадра из буфера
                        image_result = self.camera.GetNextImage(1000)
                        if image_result.IsIncomplete():
                            image_result.Release()
                            continue

                        # Конвертация и обработка (AWB, Видеозапись)
                        qimage = self._convert_to_qimage(image_result)
                        if not qimage.isNull():
                            self.frame_ready.emit(qimage)
                            fps_counter += 1
                            total_frames += 1
                        
                        image_result.Release()
                    except Exception as e:
                        continue

                # Обновление телеметрии каждую секунду
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
            logger.critical(f"Критический сбой потока камеры: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    def _apply_initial_settings(self):
        """Запись стартовых параметров в регистры камеры."""
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
            
            if not self.wb_auto:
                self.set_wb_red(self.wb_red)
                
            # Принудительно отключаем встроенный AWB камеры
            try:
                nodemap = self.camera.GetNodeMap()
                wb_auto = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceWhiteAuto"))
                if PySpin.IsAvailable(wb_auto) and PySpin.IsWritable(wb_auto):
                    wb_auto.SetIntValue(wb_auto.GetEntryByName("Off").GetValue())
            except: pass
            
        except Exception as e:
            logger.error(f"Ошибка настройки параметров: {e}")

    def _convert_to_qimage(self, image_result):
        """
        Математическое ядро потока.
        Выполняет конвертацию RAW -> RGB, гибридный баланс белого и запись видео.
        """
        try:
            image_data = image_result.GetNDArray()
            current_format = image_result.GetPixelFormat() 
            rgb = None
            
            # Дебайеризация и корректировка каналов
            if current_format == PySpin.PixelFormat_Mono8:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB)
            elif current_format == PySpin.PixelFormat_BayerRG8:
                # ВНИМАНИЕ: Используется BayerRG2BGR для исправления Red/Blue swap
                rgb = cv2.cvtColor(image_data, cv2.COLOR_BayerRG2BGR)
            elif current_format == PySpin.PixelFormat_RGB8:
                rgb = image_data
            else:
                rgb = cv2.cvtColor(image_data, cv2.COLOR_GRAY2RGB) if len(image_data.shape) == 2 else image_data

            # ГИБРИДНЫЙ АВТОБАЛАНС БЕЛОГО
            if hasattr(self, 'wb_auto') and self.wb_auto:
                current_time = time.time()
                if not hasattr(self, '_last_awb_time'):
                    self._last_awb_time = 0
                    
                # Анализируем кадр каждые 1.5 секунды для экономии CPU
                if current_time - self._last_awb_time > 1.5:
                    self._last_awb_time = current_time
                    
                    avg_r = float(np.mean(rgb[:, :, 0]))
                    avg_g = float(np.mean(rgb[:, :, 1]))
                    avg_b = float(np.mean(rgb[:, :, 2]))
                    
                    if avg_r > 5 and avg_b > 5:
                        try:
                            nodemap = self.camera.GetNodeMap()
                            ratio_node = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                            selector = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                            
                            # Расчет коэффициентов с учетом 50% демпфирования (плавности)
                            selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                            current_red = ratio_node.GetValue()
                            target_red = current_red * (avg_g / avg_r)
                            new_red = current_red * 0.5 + target_red * 0.5
                            
                            selector.SetIntValue(selector.GetEntryByName("Blue").GetValue())
                            current_blue = ratio_node.GetValue()
                            target_blue = current_blue * (avg_g / avg_b)
                            new_blue = current_blue * 0.5 + target_blue * 0.5
                            
                            # Применение параметров аппаратно
                            selector.SetIntValue(selector.GetEntryByName("Red").GetValue())
                            ratio_node.SetValue(min(ratio_node.GetMax(), max(ratio_node.GetMin(), new_red)))
                            
                            selector.SetIntValue(selector.GetEntryByName("Blue").GetValue())
                            ratio_node.SetValue(min(ratio_node.GetMax(), max(ratio_node.GetMin(), new_blue)))
                            
                            # Уведомляем UI об изменении
                            self.wb_red_calculated.emit(new_red)
                        except Exception as e:
                            pass

            # ПОТОКОВАЯ ЗАПИСЬ ВИДЕО НА ДИСК
            with QMutexLocker(self._video_lock):
                if self.is_recording:
                    if self.video_writer is None:
                        h, w = rgb.shape[:2]
                        # Маршрутизация кодека в зависимости от контейнера
                        if hasattr(self, 'record_fmt') and self.record_fmt == 'avi':
                            fourcc = cv2.VideoWriter_fourcc(*'XVID')
                        else:
                            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                            
                        self.video_writer = cv2.VideoWriter(self.record_path, fourcc, self.record_fps, (w, h))
                        logger.info(f"Video stream opened: {w}x{h} @ {self.record_fps} FPS, Codec: {self.record_fmt}")
                    
                    if self.video_writer and self.video_writer.isOpened():
                        self.video_writer.write(rgb)

            # Сборка QImage для UI
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            return img.copy()
        except Exception as e:
            return QImage()

    # МЕТОДЫ УПРАВЛЕНИЯ ПАРАМЕТРАМИ 
    
    def start_recording(self, path, fps, fmt):
        """Инициализация флагов записи видео."""
        with QMutexLocker(self._video_lock):
            self.record_path = path
            self.record_fps = fps
            self.record_fmt = fmt
            self.is_recording = True
            self.video_writer = None 

    def stop_recording(self):
        """Безопасное закрытие видеофайла."""
        with QMutexLocker(self._video_lock):
            self.is_recording = False
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
                logger.info("Видеопоток закрыт и сохранен.")

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
        """Освобождение аппаратных ресурсов при остановке потока."""
        self.stop_recording()
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
    """
    Интерфейсный контроллер. 
    Определяет Properties (Свойства) и Slots (Методы), которые можно вызывать из QML.
    """
    # СИГНАЛЫ ДЛЯ ОБНОВЛЕНИЯ UI 
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
    isRecordingChanged = Signal() 

    def __init__(self):
        super().__init__()
        # Внутреннее состояние системы
        self._status = "Готов"
        self._image_path = ""
        self._currentFps = 0.0
        self._averageFps = 0.0
        self._targetFps = 0.0
        self._efficiency = 0.0
        self._resolution = "Неизвестно"
        self._is_recording = False 
        
        self.FORMAT_MAP = {0: "Mono8", 1: "RGB8", 2: "BayerRG8"}
        
        # Настройки по умолчанию
        self.DEFAULT_CONFIG = {
            "exposure": 20000.0,
            "gain": 10.0,
            "wb_red": 1.20,
            "gamma": 1.0,
            "wb_auto": True,
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

    # ПРИВЯЗКИ (PROPERTIES) ДЛЯ QML 
    @Property(str, notify=imagePathChanged)
    def imagePath(self): return self._image_path

    @Property(bool, notify=isRecordingChanged)
    def isRecording(self): return self._is_recording

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

    # УПРАВЛЕНИЕ КАМЕРОЙ 
    @Slot()
    def start_camera(self):
        """Запуск рабочего потока камеры."""
        if self.worker and self.worker.isRunning(): return
        self.worker = CameraWorker()
        
        # Передача текущих настроек в воркер
        self.worker.exposure_time = self._exposure_value
        self.worker.gain = self._gain_value
        self.worker.wb_red = self._wb_red_value
        self.worker.gamma = self._gamma_value
        self.worker.wb_auto = self._wb_auto
        self.worker.pixel_format_str = self.FORMAT_MAP.get(self._pixel_format_index, "BayerRG8")
        
        # Подключение сигналов от воркера
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.status_changed.connect(self._update_status)
        self.worker.metrics_updated.connect(self._on_metrics_updated)
        self.worker.resolution_updated.connect(self._on_resolution_updated)
        self.worker.wb_red_calculated.connect(self._on_wb_red_calculated)
        
        self.worker.start()

    @Slot()
    def stop_camera(self):
        """Остановка рабочего потока."""
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._is_recording = False
            self.isRecordingChanged.emit()
            self._update_status("Остановлено")
            self._on_metrics_updated(0.0, 0.0, 0.0, 0.0)

    # ЗАПИСЬ ВИДЕО И СОХРАНЕНИЕ КАДРОВ 
    @Slot(str, str)
    def start_video_recording(self, file_url, fmt):
        """Запускает сохранение кадров в видеофайл."""
        if not self.worker: return
        path = QUrl(file_url).toLocalFile()
        if not path:
            path = file_url.replace("file:///", "").replace("file://", "")
        
        fps = self._targetFps if self._targetFps > 0 else 38.0
        
        self.worker.start_recording(path, fps, fmt.lower())
        self._is_recording = True
        self.isRecordingChanged.emit()
        self._update_status("ИДЕТ ЗАПИСЬ...")

    @Slot()
    def stop_video_recording(self):
        """Останавливает видеозапись."""
        if not self.worker: return
        self.worker.stop_recording()
        self._is_recording = False
        self.isRecordingChanged.emit()
        self._update_status("Камера запущена")

    @Slot(str, str, int)
    def capture_photo(self, file_url, fmt, q):
        """Копирует последний кадр из провайдера и сохраняет на диск."""
        path = QUrl(file_url).toLocalFile()
        if not path:
            path = file_url.replace("file:///", "").replace("file://", "")

        if self.provider:
            # Безопасное копирование данных (Zero-Copy защита)
            with QMutexLocker(self.provider.mutex):
                img = self.provider._current_image.copy()
            
            if not img.isNull():
                success = img.save(path, fmt.upper(), q)
                if success:
                    self._update_status("Снимок сохранен")
                else:
                    self._update_status("Ошибка сохранения")

    # ОБРАБОТЧИКИ СИГНАЛОВ (CALLBACKS) 
    def _on_frame_ready(self, qimage):
        if self.provider:
            self.provider.update_image(qimage)
            # Обновление пути заставляет QML перерисовать Image
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
        self._wb_red_value = val
        self.wbRedChanged.emit()

    # СЕТТЕРЫ И ГЕТТЕРЫ ДЛЯ ПОЛЗУНКОВ ИЗ QML 
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

    # УПРАВЛЕНИЕ КОНФИГУРАЦИЕЙ (ПРЕСЕТАМИ) 
    @Slot()
    def reset_defaults(self):
        """Возврат параметров к заводским (DEFAULT_CONFIG)."""
        self.exposureValue = self.DEFAULT_CONFIG["exposure"]
        self.gainValue = self.DEFAULT_CONFIG["gain"]
        self.wbRedValue = self.DEFAULT_CONFIG["wb_red"]
        self.wbAuto = self.DEFAULT_CONFIG["wb_auto"]
        self.pixelFormatIndex = self.DEFAULT_CONFIG["pixel_format_idx"]
        self.gammaValue = self.DEFAULT_CONFIG["gamma"]
        self._update_status("Сброс настроек")

    @Slot()
    def save_preset(self):
        """Сохранение текущего состояния ползунков в JSON."""
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
        """Загрузка состояния ползунков из JSON."""
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