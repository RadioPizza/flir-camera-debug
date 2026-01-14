# -*- coding: utf-8 -*-

"""
Main Application Entry Point.

Инициализация Qt приложения, регистрация провайдера изображений (ImageProvider)
и запуск основного цикла событий.
"""

import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

# Импортируем контроллер и класс провайдера
from CameraController import CameraController, LiveImageProvider


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 1. Создаем провайдер изображений (Zero-Copy механизм)
    image_provider = LiveImageProvider()
    
    # 2. Создаем контроллер и передаем ему провайдер
    try:
        camera_controller = CameraController()
        camera_controller.set_image_provider(image_provider)
    except Exception as e:
        print(f"Critical Initialization Error: {e}")
        sys.exit(-1)

    # 3. Настраиваем движок QML
    engine = QQmlApplicationEngine()
    
    # ВАЖНО: Регистрируем провайдер с именем "live"
    # Теперь в QML можно писать source: "image://live/..."
    engine.addImageProvider("live", image_provider)
    
    # Пробрасываем контроллер в контекст QML
    engine.rootContext().setContextProperty("cameraController", camera_controller)
    
    # Загружаем интерфейс
    qml_file = os.path.join(os.path.dirname(__file__), "main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))    

    # Проверка успешной загрузки корневого объекта
    if not engine.rootObjects():
        print("Error: Could not load main.qml")
        sys.exit(-1)
        
    sys.exit(app.exec())