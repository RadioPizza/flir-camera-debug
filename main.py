import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

from CameraController import CameraController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    try:
        camera_controller = CameraController()
    except Exception as e:
        print(f"Ошибка инициализации контроллера камеры: {e}")
        sys.exit(-1)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("cameraController", camera_controller)
    
    # Используем основной QML файл
    qml_file = os.path.join(os.path.dirname(__file__), "main.qml")
        
    engine.load(QUrl.fromLocalFile(qml_file))    

    if not engine.rootObjects():
        print("Ошибка загрузки QML интерфейса")
        sys.exit(-1)
        
    sys.exit(app.exec())