# -*- coding: utf-8 -*-

"""
Точка входа в приложение.
"""

import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

from CameraController import CameraController, LiveImageProvider

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Создаем провайдер для передачи кадров из Python в QML без копирования памяти (Zero-Copy).
    image_provider = LiveImageProvider()
    
    # Создаем главный объект управления камерой и связываем его с провайдером.
    try:
        camera_controller = CameraController()
        camera_controller.set_image_provider(image_provider)
    except Exception as e:
        print(f"Критическая ошибка инициализации контроллера: {e}")
        sys.exit(-1)

    engine = QQmlApplicationEngine()
    
    # Регистрируем провайдер под именем "live". 
    engine.addImageProvider("live", image_provider)
    
    # Пробрасываем объект camera_controller в глобальный контекст QML.
    engine.rootContext().setContextProperty("cameraController", camera_controller)
    
    qml_file = os.path.join(os.path.dirname(__file__), "main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))    

    if not engine.rootObjects():
        print("Ошибка: Не удалось загрузить main.qml")
        sys.exit(-1)
        
    # Гарантируем остановку отдельного потока камеры при закрытии окна,
    app.aboutToQuit.connect(camera_controller.stop_camera)
        
    sys.exit(app.exec())