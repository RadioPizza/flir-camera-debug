/*
 * Main Interface (main.qml)
 * Версия 3.0: Добавлено управление форматом пикселей
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
                    color: "#333"; font.pixelSize: 48; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter
                }
            }
        }

        // === ЗОНА 2: ПАНЕЛЬ УПРАВЛЕНИЯ ===
        Rectangle {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            color: "#1e1e1e"
            
            Rectangle { width: 2; height: parent.height; color: "#333"; anchors.left: parent.left }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    width: parent.width - 40
                    spacing: 25

                    Text { text: "НАСТРОЙКИ СЕНСОРА"; color: "#666"; font.pixelSize: 16; font.bold: true }

                    // --- PIXEL FORMAT SELECTOR (NEW) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text { text: "Формат пикселей"; color: "white"; font.pixelSize: 18; font.bold: true }
                        
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 50
                            // 0=Mono8, 1=RGB8, 2=BayerRG8
                            model: ["Mono8 (Ч/Б Быстрый)", "RGB8 (Цвет Обработанный)", "BayerRG8 (RAW Цвет)"]
                            currentIndex: cameraController.pixelFormatIndex
                            
                            font.pixelSize: 16
                            
                            delegate: ItemDelegate {
                                text: modelData
                                width: parent.width
                                contentItem: Text {
                                    text: modelData
                                    color: highlighted ? Material.accent : "white"
                                    font.pixelSize: 16
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle { color: highlighted ? "#333" : "transparent" }
                            }
                            
                            // При изменении отправляем индекс в контроллер
                            onActivated: (index) => {
                                cameraController.pixelFormatIndex = index
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#333" }

                    // --- SLIDER 1: GAIN ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15
                        RowLayout {
                            Text { text: "Усиление (Gain)"; color: "white"; font.pixelSize: 18; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gainValue.toFixed(1) + " dB"; color: "#00e676"; font.pixelSize: 18; font.bold: true }
                        }
                        Slider {
                            id: gainSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 40
                            from: 0.0; to: 40.0; value: cameraController.gainValue
                            onMoved: cameraController.gainValue = value
                        }
                    }

                    // --- SLIDER 2: EXPOSURE ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15
                        RowLayout {
                            Text { text: "Выдержка"; color: "white"; font.pixelSize: 18; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: Math.round(cameraController.exposureValue) + " µs"; color: "#00b0ff"; font.pixelSize: 18; font.bold: true }
                        }
                        Slider {
                            id: expSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 40
                            from: 1000.0; to: 50000.0; value: cameraController.exposureValue
                            onMoved: cameraController.exposureValue = value
                        }
                    }

                    // --- SLIDER 3: WB ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15
                        RowLayout {
                            Text { text: "Баланс (Красный)"; color: "white"; font.pixelSize: 18; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.wbRedValue.toFixed(2); color: "#ff9100"; font.pixelSize: 18; font.bold: true }
                        }
                        Slider {
                            id: wbSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 40
                            from: 0.8; to: 3.0; value: cameraController.wbRedValue
                            onMoved: cameraController.wbRedValue = value
                        }
                    }

                    Item { height: 10 }

                    // --- CONFIG BUTTONS ---
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 70
                        color: "#252525"; radius: 12; border.color: "#333"

                        RowLayout {
                            anchors.fill: parent; anchors.margins: 10; spacing: 10
                            Button {
                                Layout.fillHeight: true; Layout.preferredWidth: 80
                                onClicked: cameraController.reset_defaults()
                                contentItem: Text { text: "RESET"; color: "#ff5252"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                background: Rectangle { color: parent.down ? "#555" : "#424242"; radius: 8 }
                            }
                            Button {
                                Layout.fillHeight: true; Layout.fillWidth: true
                                onClicked: cameraController.load_preset()
                                contentItem: Text { text: "LOAD"; color: "white"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                background: Rectangle { color: parent.down ? "#333" : "transparent"; border.color: "#666"; radius: 8 }
                            }
                            Button {
                                Layout.fillHeight: true; Layout.fillWidth: true
                                onClicked: cameraController.save_preset()
                                contentItem: Text { text: "SAVE"; color: "#00e676"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                background: Rectangle { color: parent.down ? "#333" : "transparent"; border.color: "#666"; radius: 8 }
                            }
                        }
                    }

                    // --- MAIN ACTIONS ---
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 15

                        Button {
                            Layout.fillWidth: true; Layout.preferredHeight: 60
                            enabled: cameraController.status === "Камера запущена"
                            onClicked: fileDialog.open()
                            background: Rectangle { color: parent.down ? "#1565c0" : "#2196f3"; radius: 12; opacity: parent.enabled ? 1 : 0.3 }
                            contentItem: Text { text: "СНИМОК"; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }

                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            Button {
                                Layout.fillWidth: true; Layout.preferredHeight: 60
                                visible: cameraController.status !== "Камера запущена"
                                onClicked: cameraController.start_camera()
                                background: Rectangle { color: parent.down ? "#2e7d32" : "#43a047"; radius: 12 }
                                contentItem: Text { text: "СТАРТ"; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                            Button {
                                Layout.fillWidth: true; Layout.preferredHeight: 60
                                visible: cameraController.status === "Камера запущена"
                                onClicked: cameraController.stop_camera()
                                background: Rectangle { color: parent.down ? "#c62828" : "#e53935"; radius: 12 }
                                contentItem: Text { text: "СТОП"; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                        }
                    }

                    // --- TELEMETRY ---
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 100
                        color: "#252525"; radius: 12; border.color: "#333"
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 20
                            ColumnLayout {
                                Text { text: "STATUS"; color: "#888"; font.pixelSize: 12; font.bold: true }
                                Text { 
                                    text: cameraController.status === "Камера запущена" ? "ONLINE" : "OFFLINE"
                                    color: cameraController.status === "Камера запущена" ? "#00e676" : "#666" 
                                    font.pixelSize: 18; font.bold: true
                                }
                            }
                            Item { Layout.fillWidth: true }
                            RowLayout {
                                Text { text: "FPS"; color: "#aaa"; font.pixelSize: 18; font.bold: true; verticalAlignment: Text.AlignBottom }
                                Text {
                                    text: Math.round(cameraController.currentFps * 10) / 10
                                    color: cameraController.currentFps > 20 ? "#00e676" : "#ff3d00"
                                    font.pixelSize: 36; font.bold: true
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