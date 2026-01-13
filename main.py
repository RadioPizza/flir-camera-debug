import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

# Импортируем контроллер и класс провайдера
from CameraController import CameraController, LiveImageProvider

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 1. Создаем провайдер изображений
    image_provider = LiveImageProvider()
    
    # 2. Создаем контроллер и передаем ему провайдер
    try:
        camera_controller = CameraController()
        camera_controller.set_image_provider(image_provider)
    except Exception as e:
        print(f"Ошибка инициализации: {e}")
        sys.exit(-1)

    # 3. Настраиваем движок QML
    engine = QQmlApplicationEngine()
    
    # ВАЖНО: Регистрируем провайдер с именем "live"
    # Теперь в QML можно писать source: "image://live/..."
    engine.addImageProvider("live", image_provider)
    
    # Пробрасываем контроллер в QML
    engine.rootContext().setContextProperty("cameraController", camera_controller)
    
    # Загружаем интерфейс
    qml_file = os.path.join(os.path.dirname(__file__), "main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))    

    if not engine.rootObjects():
        print("Ошибка загрузки QML")
        sys.exit(-1)
        
    sys.exit(app.exec())