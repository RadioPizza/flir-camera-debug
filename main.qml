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
    height: 800
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
                mipmap: true
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
                Text {
                    text: "SYSTEM STANDBY"
                    color: "#444"
                    font.pixelSize: 20
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
                width: 2; height: parent.height; color: "#333"; anchors.left: parent.left 
            }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    width: parent.width - 40
                    spacing: 30

                    Text {
                        text: "НАСТРОЙКИ СЕНСОРОВ"
                        color: "#666"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    // --- SLIDER 1: УСИЛЕНИЕ (GAIN) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15
                        RowLayout {
                            Text { text: "Усиление (дБ)"; color: "white"; font.pixelSize: 22; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gainValue.toFixed(1); color: "#00e676"; font.pixelSize: 22; font.bold: true }
                        }
                        Slider {
                            id: gainSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 50
                            from: 0.0; to: 40.0; value: cameraController.gainValue
                            handle: Rectangle {
                                x: gainSlider.leftPadding + gainSlider.visualPosition * (gainSlider.availableWidth - width)
                                y: gainSlider.topPadding + gainSlider.availableHeight / 2 - height / 2
                                width: 48; height: 48; radius: 24
                                color: gainSlider.pressed ? "#00e676" : "#f6f6f6"; border.color: "#333"
                            }
                            onMoved: cameraController.gainValue = value
                        }
                    }

                    // --- [НОВОЕ] SLIDER 2: ВЫДЕРЖКА (EXPOSURE) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15
                        RowLayout {
                            Text { text: "Выдержка (мкс)"; color: "white"; font.pixelSize: 22; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: Math.round(cameraController.exposureValue); color: "#00b0ff"; font.pixelSize: 22; font.bold: true }
                        }
                        Slider {
                            id: expSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 50
                            from: 1000.0; to: 50000.0; // Диапазон от 1мс до 50мс
                            value: cameraController.exposureValue
                            
                            handle: Rectangle {
                                x: expSlider.leftPadding + expSlider.visualPosition * (expSlider.availableWidth - width)
                                y: expSlider.topPadding + expSlider.availableHeight / 2 - height / 2
                                width: 48; height: 48; radius: 24
                                color: expSlider.pressed ? "#00b0ff" : "#f6f6f6"; border.color: "#333"
                            }
                            onMoved: cameraController.exposureValue = value
                        }
                    }

                    // --- SLIDER 3: БАЛАНС (RED RATIO) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15 
                        RowLayout {
                            Text { text: "Баланс (Красный)"; color: "white"; font.pixelSize: 22; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.wbRedValue.toFixed(2); color: "#ff9100"; font.pixelSize: 22; font.bold: true }
                        }
                        Slider {
                            id: wbSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 50
                            from: 0.8; to: 3.0; value: cameraController.wbRedValue
                            handle: Rectangle {
                                x: wbSlider.leftPadding + wbSlider.visualPosition * (wbSlider.availableWidth - width)
                                y: wbSlider.topPadding + wbSlider.availableHeight / 2 - height / 2
                                width: 48; height: 48; radius: 24
                                color: wbSlider.pressed ? "#ff9100" : "#f6f6f6"; border.color: "#333"
                            }
                            onMoved: cameraController.wbRedValue = value
                        }
                    }

                    Item { Layout.fillHeight: true } 

                    // --- КНОПКИ ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 20

                        Button {
                            Layout.fillWidth: true; Layout.preferredHeight: 90
                            enabled: cameraController.status === "Камера запущена"
                            onClicked: fileDialog.open()
                            background: Rectangle { color: parent.down ? "#1565c0" : "#2196f3"; radius: 16; opacity: parent.enabled ? 1 : 0.3 }
                            contentItem: Text { text: "СНИМОК"; font.pixelSize: 24; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }

                        Button {
                            Layout.fillWidth: true; Layout.preferredHeight: 90 
                            visible: cameraController.status !== "Камера запущена"
                            onClicked: cameraController.start_camera()
                            background: Rectangle { color: parent.down ? "#2e7d32" : "#43a047"; radius: 16 }
                            contentItem: Text { text: "СТАРТ"; font.pixelSize: 24; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }

                        Button {
                            Layout.fillWidth: true; Layout.preferredHeight: 90 
                            visible: cameraController.status === "Камера запущена"
                            onClicked: cameraController.stop_camera()
                            background: Rectangle { color: parent.down ? "#c62828" : "#e53935"; radius: 16 }
                            contentItem: Text { text: "СТОП"; font.pixelSize: 24; font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }

                    // --- ТЕЛЕМЕТРИЯ ---
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 100
                        Layout.topMargin: 20; color: "#252525"; radius: 16; border.color: "#333"

                        RowLayout {
                            anchors.fill: parent;
                            ColumnLayout {
                                spacing: 4
                                Text { text: "СИСТЕМА"; color: "#888"; font.pixelSize: 14; font.bold: true }
                                Text { 
                                    text: cameraController.status === "Камера запущена" ? "ONLINE" : "OFFLINE"
                                    color: cameraController.status === "Камера запущена" ? "#00e676" : "#666" 
                                    font.pixelSize: 22; font.bold: true
                                }
                            }
                            Item { Layout.fillWidth: true } 
                            RowLayout {
                                spacing: 20
                                Text { text: "FPS"; color: "#aaa"; font.pixelSize: 24; font.bold: true; verticalAlignment: Text.AlignBottom; bottomPadding: 6 }
                                Text {
                                    text: Math.round(cameraController.currentFps * 10) / 10
                                    color: cameraController.currentFps > 25 ? "#00e676" : (cameraController.currentFps > 10 ? "#ffeb3b" : "#ff3d00")
                                    font.pixelSize: 48; font.bold: true
                                }
                            }
                        }
                    }
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