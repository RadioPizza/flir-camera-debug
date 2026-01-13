import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs
import QtQuick.Controls.Material // Используем Material Design для планшетов

ApplicationWindow {
    id: window
    title: "FLIR Mobile Command"
    visible: true
    width: 1280
    height: 800
    color: "#121212"

    // Настраиваем тему Material (Темная)
    Material.theme: Material.Dark
    Material.accent: Material.LightGreen

    Component.onCompleted: window.showMaximized()

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // === ЗОНА 1: ВИДЕОПОТОК (Слева, занимает максимум места) ===
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "black"

            Image {
                id: camView
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                source: cameraController.imagePath
                cache: false
                asynchronous: false
                mipmap: true
            }

            // Оверлей с телеметрией (FPS и Статус)
            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: 20
                width: 280
                height: 100
                color: "#aa000000" // Полупрозрачный фон
                radius: 12
                border.color: "#333"
                border.width: 2

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 5
                    
                    Text {
                        text: "FPS: " + Math.round(cameraController.currentFps * 10) / 10
                        color: cameraController.currentFps > 25 ? "#00ff00" : "#ff3333"
                        font.pixelSize: 32 // Крупный шрифт
                        font.bold: true
                    }
                    Text {
                        text: cameraController.status
                        color: "#cccccc"
                        font.pixelSize: 18
                    }
                }
            }
        }

        // === ЗОНА 2: КОМАНДНАЯ ПАНЕЛЬ (Справа, фиксированная ширина) ===
        Rectangle {
            Layout.preferredWidth: 380 // Широкая панель для удобства пальцев
            Layout.fillHeight: true
            color: "#1e1e1e"
            
            // Разделительная линия
            Rectangle { 
                width: 2; height: parent.height; color: "#333"; anchors.left: parent.left 
            }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    width: parent.width - 40
                    spacing: 25 // Большие отступы между элементами

                    Text {
                        text: "НАСТРОЙКИ"
                        color: "#666"
                        font.pixelSize: 18
                        font.bold: true
                    }

                    // --- Слайдер GAIN ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        
                        RowLayout {
                            Text { text: "Gain (dB)"; color: "white"; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gainValue.toFixed(1); color: "#00e676"; font.pixelSize: 20; font.bold: true }
                        }

                        // Кастомный большой слайдер
                        Slider {
                            id: gainSlider
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            from: 0.0
                            to: 40.0
                            value: cameraController.gainValue
                            
                            // Увеличиваем "ручку" для пальца
                            handle: Rectangle {
                                x: gainSlider.leftPadding + gainSlider.visualPosition * (gainSlider.availableWidth - width)
                                y: gainSlider.topPadding + gainSlider.availableHeight / 2 - height / 2
                                width: 32
                                height: 32
                                radius: 16
                                color: gainSlider.pressed ? "#00e676" : "#f6f6f6"
                                border.color: "#333"
                            }
                            
                            onMoved: cameraController.gainValue = value
                        }
                    }

                    // --- Слайдер GAMMA ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        
                        RowLayout {
                            Text { text: "Gamma"; color: "white"; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gammaValue.toFixed(2); color: "#2979ff"; font.pixelSize: 20; font.bold: true }
                        }

                        Slider {
                            id: gammaSlider
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            from: 0.1
                            to: 4.0
                            value: cameraController.gammaValue
                            
                            handle: Rectangle {
                                x: gammaSlider.leftPadding + gammaSlider.visualPosition * (gammaSlider.availableWidth - width)
                                y: gammaSlider.topPadding + gammaSlider.availableHeight / 2 - height / 2
                                width: 32
                                height: 32
                                radius: 16
                                color: gammaSlider.pressed ? "#2979ff" : "#f6f6f6"
                                border.color: "#333"
                            }

                            onMoved: cameraController.gammaValue = value
                        }
                        
                        // Кнопка-переключатель для Gamma
                        Switch {
                            text: "Gamma Enable"
                            checked: cameraController.gammaEnabled
                            font.pixelSize: 18
                            onCheckedChanged: cameraController.gammaEnabled = checked
                            Layout.alignment: Qt.AlignRight
                            
                            // Кастомизация цвета
                            indicator: Rectangle {
                                implicitWidth: 56
                                implicitHeight: 32
                                x: parent.leftPadding
                                y: parent.height / 2 - height / 2
                                radius: 16
                                color: parent.checked ? "#2979ff" : "#333"
                                border.color: parent.checked ? "#2979ff" : "#cccccc"
                                
                                Rectangle {
                                    x: parent.parent.checked ? parent.width - width - 2 : 2
                                    width: 28
                                    height: 28
                                    radius: 14
                                    y: 2
                                    color: "white"
                                    Behavior on x { NumberAnimation { duration: 100 } }
                                }
                            }
                            contentItem: Text {
                                text: parent.text
                                font: parent.font
                                color: "white"
                                leftPadding: parent.indicator.width + spacing
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }

                    // Распорка (пружина), чтобы кнопки прижались вниз
                    Item { Layout.fillHeight: true }

                    // --- БЛОК КРУПНЫХ КНОПОК ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15

                        // Кнопка СНИМОК (Синяя)
                        Button {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80 // Большая высота для пальца
                            enabled: cameraController.status === "Камера запущена"
                            onClicked: fileDialog.open()

                            background: Rectangle {
                                color: parent.down ? "#1565c0" : "#2196f3"
                                radius: 12
                                opacity: parent.enabled ? 1 : 0.3
                            }
                            contentItem: RowLayout {
                                anchors.centerIn: parent
                                Text {
                                    text: "СОХРАНИТЬ ФОТО"
                                    font.pixelSize: 20
                                    font.bold: true
                                    color: "white"
                                }
                            }
                        }

                        // Кнопка СТАРТ (Зеленая)
                        Button {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80
                            visible: cameraController.status !== "Камера запущена"
                            onClicked: cameraController.start_camera()

                            background: Rectangle {
                                color: parent.down ? "#2e7d32" : "#43a047"
                                radius: 12
                            }
                            contentItem: Text {
                                text: "ЗАПУСК КАМЕРУ"
                                font.pixelSize: 22
                                font.bold: true
                                color: "white"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        // Кнопка СТОП (Красная)
                        Button {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80
                            visible: cameraController.status === "Камера запущена"
                            onClicked: cameraController.stop_camera()

                            background: Rectangle {
                                color: parent.down ? "#c62828" : "#e53935"
                                radius: 12
                            }
                            contentItem: Text {
                                text: "ОСТАНОВИТЬ"
                                font.pixelSize: 22
                                font.bold: true
                                color: "white"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    
                    // Нижний отступ
                    Item { height: 10 }
                }
            }
        }
    }

    FileDialog {
        id: fileDialog
        title: "Сохранить кадр"
        currentFolder: StandardPaths.standardLocations(StandardPaths.PicturesLocation)[0]
        nameFilters: ["JPEG Image (*.jpg)", "PNG Image (*.png)"]
        onAccepted: {
            var path = selectedFile.toString()
            if (Qt.platform.os === "windows") {
                path = path.replace(/^(file:\/{3})|(file:)/, "")
            } else {
                path = path.replace(/^(file:)/, "")
            }
            cameraController.capture_photo(path, "JPEG", 95)
        }
    }
}