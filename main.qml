/*
 * Main Interface (main.qml)
 * Исправлена компоновка полей и перенос текста в телеметрии
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs
import QtQuick.Controls.Material

ApplicationWindow {
    id: window
    title: "FLIR Mobile Command"
    visible: true
    width: 1280
    height: 900
    color: "#121212"

    Material.theme: Material.Dark
    Material.accent: Material.LightGreen

    Component.onCompleted: window.showMaximized()

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // === ЗОНА 1: ВИДЕОПОТОК ===
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
            }

            Column {
                anchors.centerIn: parent
                visible: cameraController.status !== "Камера запущена"
                spacing: 15
                Text {
                    text: "NO SIGNAL"
                    color: "#333"
                    font.pixelSize: 48
                    font.bold: true
                    anchors.horizontalCenter: parent.horizontalCenter
                }
            }
        }

        // === ЗОНА 2: ПАНЕЛЬ УПРАВЛЕНИЯ ===
        Rectangle {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            color: "#1e1e1e"
            
            Rectangle { 
                width: 2; height: parent.height; 
                color: "#333"; anchors.left: parent.left 
            }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    // ИСПРАВЛЕНИЕ: Используем всю ширину ScrollView
                    width: parent.width 
                    spacing: 25

                    Text { 
                        text: "НАСТРОЙКИ СЕНСОРА"
                        color: "#666"; font.pixelSize: 14; font.bold: true 
                    }

                    // --- PIXEL FORMAT SELECTOR ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { 
                            text: "Формат пикселей"
                            color: "white"; font.pixelSize: 16; font.bold: true 
                        }
                        
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 45
                            model: ["Mono8 (Ч/Б Быстрый)", "RGB8 (Цвет Обработанный)", "BayerRG8 (RAW Цвет)"]
                            currentIndex: cameraController.pixelFormatIndex
                            font.pixelSize: 14
                            onActivated: (index) => cameraController.pixelFormatIndex = index
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#333" }

                    // --- SLIDER 1: GAIN ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Усиление (Gain)"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            Text { 
                                text: cameraController.gainValue.toFixed(1) + " dB"
                                color: "#00e676"; font.pixelSize: 16; font.bold: true 
                            }
                        }
                        Slider {
                            Layout.fillWidth: true; Layout.preferredHeight: 32
                            from: 0.0; to: 40.0; value: cameraController.gainValue
                            onMoved: cameraController.gainValue = value
                        }
                    }

                    // --- SLIDER 2: EXPOSURE ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Выдержка"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            Text { 
                                text: Math.round(cameraController.exposureValue) + " µs"
                                color: "#00b0ff"; font.pixelSize: 16; font.bold: true 
                            }
                        }
                        Slider {
                            Layout.fillWidth: true; Layout.preferredHeight: 32
                            from: 1000.0; to: 50000.0; value: cameraController.exposureValue
                            onMoved: cameraController.exposureValue = value
                        }
                    }

                    // --- SLIDER 3: WHITE BALANCE (RED) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Баланс (Красный)"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            Text { 
                                text: cameraController.wbRedValue.toFixed(2)
                                color: "#ff9100"; font.pixelSize: 16; font.bold: true 
                            }
                        }
                        Slider {
                            Layout.fillWidth: true; Layout.preferredHeight: 32
                            from: 0.8; to: 3.0; value: cameraController.wbRedValue
                            onMoved: cameraController.wbRedValue = value
                        }
                    }

                    Item { Layout.preferredHeight: 10 }

                    // --- CONFIG BUTTONS ---
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Button {
                            text: "RESET"; Layout.fillWidth: true
                            onClicked: cameraController.reset_defaults()
                            Material.foreground: Material.Red
                        }
                        Button {
                            text: "LOAD"; Layout.fillWidth: true
                            onClicked: cameraController.load_preset()
                        }
                        Button {
                            text: "SAVE"; Layout.fillWidth: true
                            onClicked: cameraController.save_preset()
                            Material.foreground: Material.Green
                        }
                    }

                    // --- MAIN ACTIONS ---
                    Button {
                        text: "СНИМОК"
                        Layout.fillWidth: true; Layout.preferredHeight: 55
                        enabled: cameraController.status === "Камера запущена"
                        onClicked: fileDialog.open()
                        Material.background: Material.Blue
                    }

                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        Button {
                            text: "СТАРТ"; Layout.fillWidth: true; Layout.preferredHeight: 55
                            visible: cameraController.status !== "Камера запущена"
                            onClicked: cameraController.start_camera()
                            Material.background: Material.Green
                        }
                        Button {
                            text: "СТОП"; Layout.fillWidth: true; Layout.preferredHeight: 55
                            visible: cameraController.status === "Камера запущена"
                            onClicked: cameraController.stop_camera()
                            Material.background: Material.Red
                        }
                    }

                    // --- TELEMETRY ---
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 160
                        color: "#252525"; radius: 10; border.color: "#333"

                        GridLayout {
                            anchors.fill: parent; anchors.margins: 12
                            columns: 2; rowSpacing: 12; columnSpacing: 10

                            ColumnLayout {
                                Text { text: "STATUS"; color: "#666"; font.pixelSize: 11; font.bold: true }
                                Text { 
                                    text: cameraController.status === "Камера запущена" ? "ONLINE" : "OFFLINE"
                                    color: cameraController.status === "Камера запущена" ? "#00e676" : "#666"
                                    font.pixelSize: 14; font.bold: true
                                }
                            }

                            ColumnLayout {
                                Layout.alignment: Qt.AlignRight
                                Text { 
                                    text: "RESOLUTION"; color: "#666"; font.pixelSize: 11; 
                                    font.bold: true; Layout.alignment: Qt.AlignRight 
                                }
                                Text { 
                                    text: cameraController.resolution
                                    color: "#00b0ff"; font.pixelSize: 14; font.bold: true
                                    Layout.alignment: Qt.AlignRight
                                }
                            }

                            ColumnLayout {
                                Text { text: "CUR / AVG FPS"; color: "#666"; font.pixelSize: 11; font.bold: true }
                                RowLayout {
                                    Text {
                                        text: cameraController.currentFps.toFixed(1)
                                        color: cameraController.currentFps > 20 ? "#00e676" : "#ff3d00"
                                        font.pixelSize: 20; font.bold: true
                                    }
                                    Text { text: "/"; color: "#444"; font.pixelSize: 16 }
                                    Text {
                                        text: cameraController.averageFps.toFixed(1)
                                        color: "#ff9100"; font.pixelSize: 16; font.bold: true
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.alignment: Qt.AlignRight
                                Text { 
                                    // ИСПРАВЛЕНИЕ: Разрешаем перенос для длинного заголовка
                                    text: "TARGET / EFFICIENCY"; color: "#666"; font.pixelSize: 11; 
                                    font.bold: true; Layout.alignment: Qt.AlignRight;
                                    wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignRight;
                                    Layout.preferredWidth: 100
                                }
                                RowLayout {
                                    Layout.alignment: Qt.AlignRight
                                    Text {
                                        text: cameraController.targetFps.toFixed(1)
                                        color: "#888"; font.pixelSize: 14; font.bold: true
                                    }
                                    Text { text: "|"; color: "#444"; font.pixelSize: 14 }
                                    Text {
                                        text: cameraController.efficiency.toFixed(1) + "%"
                                        color: cameraController.efficiency > 90 ? "#00e676" : "#ff9100"
                                        font.pixelSize: 16; font.bold: true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    FileDialog {
        id: fileDialog
        title: "Сохранить кадр"
        currentFolder: StandardPaths.standardLocations(StandardPaths.PicturesLocation)[0]
        onAccepted: {
            var path = selectedFile.toString().replace(/^(file:\/{3})|(file:)/, "")
            cameraController.capture_photo(path, "JPEG", 95)
        }
    }
}