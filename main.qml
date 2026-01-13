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

            // Заглушка, если камера не активна
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
            
            // Разделитель
            Rectangle { 
                width: 2; height: parent.height; color: "#333"; anchors.left: parent.left 
            }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    width: parent.width - 40
                    spacing: 30 // Увеличили отступы между блоками

                    Text {
                        text: "НАСТРОЙКИ СЕНСОРОВ"
                        color: "#666"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    // --- SLIDER: GAIN ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Text { text: "Gain (dB)"; color: "white"; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gainValue.toFixed(1); color: "#00e676"; font.pixelSize: 20; font.bold: true }
                        }
                        Slider {
                            id: gainSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 40; from: 0.0; to: 40.0; value: cameraController.gainValue
                            handle: Rectangle {
                                x: gainSlider.leftPadding + gainSlider.visualPosition * (gainSlider.availableWidth - width)
                                y: gainSlider.topPadding + gainSlider.availableHeight / 2 - height / 2
                                width: 32; height: 32; radius: 16
                                color: gainSlider.pressed ? "#00e676" : "#f6f6f6"; border.color: "#333"
                            }
                            onMoved: cameraController.gainValue = value
                        }
                    }

                    // --- SLIDER: GAMMA ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 15 // Чуть больше воздуха
                        RowLayout {
                            Text { text: "Gamma"; color: "white"; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Text { text: cameraController.gammaValue.toFixed(2); color: "#2979ff"; font.pixelSize: 20; font.bold: true }
                        }
                        Slider {
                            id: gammaSlider
                            Layout.fillWidth: true; Layout.preferredHeight: 40; from: 0.1; to: 4.0; value: cameraController.gammaValue
                            handle: Rectangle {
                                x: gammaSlider.leftPadding + gammaSlider.visualPosition * (gammaSlider.availableWidth - width)
                                y: gammaSlider.topPadding + gammaSlider.availableHeight / 2 - height / 2
                                width: 32; height: 32; radius: 16
                                color: gammaSlider.pressed ? "#2979ff" : "#f6f6f6"; border.color: "#333"
                            }
                            onMoved: cameraController.gammaValue = value
                        }
                        
                        // [ИЗМЕНЕНИЕ] Переключатель Gamma в отдельном RowLayout
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 15 
                            
                            // Сам переключатель (Слева)
                            Switch {
                                id: gammaSw
                                checked: cameraController.gammaEnabled
                                onCheckedChanged: cameraController.gammaEnabled = checked
                                
                                indicator: Rectangle {
                                    implicitWidth: 64; implicitHeight: 38; radius: 19 // Увеличили размер свитча
                                    color: gammaSw.checked ? "#2979ff" : "#333"
                                    border.color: gammaSw.checked ? "#2979ff" : "#cccccc"
                                    Rectangle {
                                        x: gammaSw.checked ? parent.width - width - 4 : 4
                                        width: 30; height: 30; radius: 15; y: 4; color: "white"
                                        Behavior on x { NumberAnimation { duration: 100 } }
                                    }
                                }
                            }
                            
                            // Текст (Справа)
                            Text {
                                text: "Gamma Enable"
                                color: gammaSw.checked ? "white" : "#777"
                                font.pixelSize: 20 // Крупнее шрифт
                                font.bold: true
                            }
                            
                            Item { Layout.fillWidth: true } // Прижать влево
                        }
                    }

                    Item { Layout.fillHeight: true } // Пружина

                    // --- КНОПКИ (Увеличены) ---
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 20

                        Button {
                            Layout.fillWidth: true; 
                            Layout.preferredHeight: 90 // Было 70, стало 90
                            enabled: cameraController.status === "Камера запущена"
                            onClicked: fileDialog.open()
                            background: Rectangle { color: parent.down ? "#1565c0" : "#2196f3"; radius: 16; opacity: parent.enabled ? 1 : 0.3 }
                            contentItem: Text { 
                                text: "СНИМОК"; 
                                font.pixelSize: 24; // Было 20
                                font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter 
                            }
                        }

                        Button {
                            Layout.fillWidth: true; 
                            Layout.preferredHeight: 90 
                            visible: cameraController.status !== "Камера запущена"
                            onClicked: cameraController.start_camera()
                            background: Rectangle { color: parent.down ? "#2e7d32" : "#43a047"; radius: 16 }
                            contentItem: Text { 
                                text: "СТАРТ"; 
                                font.pixelSize: 24; 
                                font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter 
                            }
                        }

                        Button {
                            Layout.fillWidth: true; 
                            Layout.preferredHeight: 90 
                            visible: cameraController.status === "Камера запущена"
                            onClicked: cameraController.stop_camera()
                            background: Rectangle { color: parent.down ? "#c62828" : "#e53935"; radius: 16 }
                            contentItem: Text { 
                                text: "СТОП"; 
                                font.pixelSize: 24; 
                                font.bold: true; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter 
                            }
                        }
                    }

                    // --- [ИЗМЕНЕНИЕ] БЛОК ТЕЛЕМЕТРИИ (Увеличен) ---
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        Layout.topMargin: 20
                        color: "#252525"
                        radius: 16
                        border.color: "#333"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 20 // Больше отступ внутри
                            
                            // Надпись статуса
                            ColumnLayout {
                                spacing: 4
                                Text { 
                                    text: "СИСТЕМА"; color: "#888"; font.pixelSize: 14; font.bold: true 
                                }
                                Text { 
                                    text: cameraController.status === "Камера запущена" ? "ONLINE" : "OFFLINE"
                                    color: cameraController.status === "Камера запущена" ? "#00e676" : "#666" 
                                    font.pixelSize: 22 // Увеличили
                                    font.bold: true
                                }
                            }
                            
                            Item { Layout.fillWidth: true } // Распорка

                            // Счетчик FPS
                            RowLayout {
                                spacing: 15
                                Text { 
                                    text: "FPS"
                                    color: "#aaa"
                                    font.pixelSize: 24
                                    font.bold: true
                                    verticalAlignment: Text.AlignBottom
                                }
                                Text {
                                    text: Math.round(cameraController.currentFps * 10) / 10
                                    color: cameraController.currentFps > 25 ? "#00e676" : (cameraController.currentFps > 10 ? "#ffeb3b" : "#ff3d00")
                                    font.pixelSize: 42 // Очень крупно, чтобы влезало и читалось
                                    font.bold: true
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