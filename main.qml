import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs 

ApplicationWindow {
    id: window
    title: "FLIR Camera Tool - Advanced Control"
    visible: true
    width: 1280
    height: 800
    color: "#121212" // Глубокий черный фон

    Component.onCompleted: window.showMaximized()

    // Основная разметка: Слева картинка, Справа панель
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // === ЛЕВАЯ ЧАСТЬ: ИЗОБРАЖЕНИЕ ===
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#000000"
            
            // Видеопоток
            Image {
                id: camView
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                
                // Используем наш быстрый Image Provider
                source: cameraController.imagePath 
                
                cache: false
                asynchronous: false
                mipmap: true // Немного сглаживания при масштабировании
            }

            // Оверлей с FPS в углу картинки
            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: 10
                width: 80
                height: 30
                color: "#80000000"
                radius: 4
                
                Text {
                    anchors.centerIn: parent
                    text: "FPS: " + Math.round(cameraController.currentFps * 10) / 10
                    color: cameraController.currentFps > 25 ? "#00ff00" : (cameraController.currentFps > 10 ? "yellow" : "red")
                    font.bold: true
                }
            }

            // Заглушка "Камера остановлена"
            Column {
                anchors.centerIn: parent
                visible: cameraController.status !== "Камера запущена"
                spacing: 10
                
                Text {
                    text: "NO SIGNAL"
                    color: "#333"
                    font.pixelSize: 40
                    font.bold: true
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Text {
                    text: cameraController.status
                    color: "#666"
                    font.pixelSize: 16
                    anchors.horizontalCenter: parent.horizontalCenter
                }
            }
        }

        // === ПРАВАЯ ЧАСТЬ: ПАНЕЛЬ УПРАВЛЕНИЯ ===
        Rectangle {
            Layout.preferredWidth: 320
            Layout.fillHeight: true
            color: "#1e1e1e" // Темно-серый фон панели
            
            // Линия-разделитель
            Rectangle {
                width: 1
                height: parent.height
                color: "#333"
                anchors.left: parent.left
            }

            ScrollView {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                anchors.topMargin: 10
                clip: true

                ColumnLayout {
                    width: parent.width - 20
                    spacing: 15

                    // --- Секция 1: Статус ---
                    GroupBox {
                        title: "System Status"
                        Layout.fillWidth: true
                        background: Rectangle { color: "transparent"; border.color: "#444"; radius: 4 }
                        label: Text { text: parent.title; color: "#aaa"; font.bold: true }

                        ColumnLayout {
                            spacing: 5
                            Text { 
                                text: "Resolution: " + (cameraController.cameraInfo["resolution"] || "N/A")
                                color: "#ddd" 
                            }
                            Text { 
                                text: "Format: " + (cameraController.cameraInfo["pixel_format"] || "N/A")
                                color: "#ddd" 
                            }
                            Text { 
                                text: "Packet Size: " + (cameraController.cameraInfo["packet_size"] || "Auto")
                                color: "#ddd" 
                            }
                        }
                    }

                    // --- Секция 2: Gain (Усиление) ---
                    GroupBox {
                        title: "Gain Control (dB)"
                        Layout.fillWidth: true
                        background: Rectangle { color: "transparent"; border.color: "#444"; radius: 4 }
                        label: Text { text: parent.title; color: "#aaa"; font.bold: true }

                        ColumnLayout {
                            Layout.fillWidth: true
                            
                            RowLayout {
                                Layout.fillWidth: true
                                Slider {
                                    id: gainSlider
                                    Layout.fillWidth: true
                                    from: 0.0
                                    to: 40.0
                                    value: cameraController.gainValue
                                    
                                    // Обновляем backend только когда отпускаем (чтобы не спамить), 
                                    // или можно live:
                                    onMoved: cameraController.gainValue = value
                                }
                                Text {
                                    text: gainSlider.value.toFixed(1)
                                    color: "white"
                                    Layout.preferredWidth: 40
                                }
                            }
                        }
                    }

                    // --- Секция 3: Gamma ---
                    GroupBox {
                        title: "Gamma Correction"
                        Layout.fillWidth: true
                        background: Rectangle { color: "transparent"; border.color: "#444"; radius: 4 }
                        label: Text { text: parent.title; color: "#aaa"; font.bold: true }

                        ColumnLayout {
                            Layout.fillWidth: true
                            
                            CheckBox {
                                text: "Enable Gamma"
                                checked: cameraController.gammaEnabled
                                onCheckedChanged: cameraController.gammaEnabled = checked
                                
                                contentItem: Text {
                                    text: parent.text
                                    color: "white"
                                    leftPadding: parent.indicator.width + 4
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Slider {
                                    id: gammaSlider
                                    Layout.fillWidth: true
                                    from: 0.1
                                    to: 4.0
                                    value: cameraController.gammaValue
                                    enabled: cameraController.gammaEnabled
                                    
                                    onMoved: cameraController.gammaValue = value
                                }
                                Text {
                                    text: gammaSlider.value.toFixed(2)
                                    color: cameraController.gammaEnabled ? "white" : "#555"
                                    Layout.preferredWidth: 40
                                }
                            }
                        }
                    }

                    // Распределитель пустого пространства
                    Item { Layout.fillHeight: true } 

                    // --- Секция 4: Кнопки ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        // Кнопка Старт
                        Button {
                            text: "START STREAM"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            visible: cameraController.status !== "Камера запущена"
                            onClicked: cameraController.start_camera()
                            
                            background: Rectangle {
                                color: parent.down ? "#1a661a" : "#228822"
                                radius: 4
                            }
                            contentItem: Text {
                                text: parent.text
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        // Кнопка Стоп
                        Button {
                            text: "STOP STREAM"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            visible: cameraController.status === "Камера запущена"
                            onClicked: cameraController.stop_camera()
                            
                            background: Rectangle {
                                color: parent.down ? "#661a1a" : "#882222"
                                radius: 4
                            }
                            contentItem: Text {
                                text: parent.text
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        
                        // Кнопка Снимок
                        Button {
                            text: "SAVE SNAPSHOT"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            enabled: cameraController.status === "Камера запущена"
                            onClicked: fileDialog.open()
                            
                            background: Rectangle {
                                color: parent.enabled ? (parent.down ? "#224488" : "#3355aa") : "#333"
                                radius: 4
                            }
                            contentItem: Text {
                                text: parent.text
                                color: parent.enabled ? "white" : "#555"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    
                    // Отступ снизу
                    Item { height: 20 }
                }
            }
        }
    }
    
    // Диалог сохранения файла
    FileDialog {
        id: fileDialog
        title: "Save Snapshot"
        currentFolder: StandardPaths.standardLocations(StandardPaths.PicturesLocation)[0]
        nameFilters: ["JPEG Image (*.jpg)", "PNG Image (*.png)"]
        onAccepted: {
            var path = selectedFile.toString()
            // Удаляем префикс file:// для корректной работы в Python
            if (Qt.platform.os === "windows") {
                path = path.replace(/^(file:\/{3})|(file:)/, "")
            } else {
                path = path.replace(/^(file:)/, "")
            }
            
            // Вызываем метод сохранения в Python
            // Формат берем из расширения или передаем дефолтный
            cameraController.capture_photo(path, "JPEG", 95)
        }
    }
}