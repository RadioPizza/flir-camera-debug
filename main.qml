/*
 * Main Interface (main.qml)
 * Главный экран управления промышленной камерой.
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

    // Применяем темную тему Material Design
    Material.theme: Material.Dark
    Material.accent: Material.LightGreen

    Component.onCompleted: window.showMaximized()

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ЗОНА 1: ВЬЮВЕР (ВИДЕОПОТОК) 
       
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "black"

            Image {
                id: camView
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                // Привязка к провайдеру: при изменении cameraController.imagePath 
                // изображение автоматически перезапрашивается
                source: cameraController.imagePath
                cache: false
                asynchronous: false
            }

            // Заглушка, отображаемая при выключенной камере
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

        
        // ЗОНА 2: ПАНЕЛЬ УПРАВЛЕНИЯ 
        
        Rectangle {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            color: "#1e1e1e"
            
            // Визуальный разделитель (рамка слева)
            Rectangle { 
                width: 2; height: parent.height; 
                color: "#333"; anchors.left: parent.left 
            }

            ScrollView {
                anchors.fill: parent
                anchors.margins: 20
                clip: true

                ColumnLayout {
                    width: parent.width 
                    spacing: 25

                    Text { 
                        text: "НАСТРОЙКИ СЕНСОРА"
                        color: "#666"; font.pixelSize: 14; font.bold: true 
                    }

                    //  ФОРМАТ ПИКСЕЛЕЙ (ComboBox) 
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "Формат пикселей"; color: "white"; font.pixelSize: 16; font.bold: true }
                        
                        ComboBox {
                            Layout.fillWidth: true; Layout.preferredHeight: 45
                            model: ["Mono8 (Ч/Б Быстрый)", "RGB8 (Цвет Обработанный)", "BayerRG8 (RAW Цвет)"]
                            currentIndex: cameraController.pixelFormatIndex
                            font.pixelSize: 14
                            onActivated: (index) => cameraController.pixelFormatIndex = index
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#333" }

                    // УСИЛЕНИЕ / GAIN (Слайдер) 
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Усиление (Gain)"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true
                                // Защита от переполнения: длинный текст обрезается троеточием (...)
                                elide: Text.ElideRight
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

                    // ВЫДЕРЖКА / EXPOSURE (Слайдер) 
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

                    // БАЛАНС БЕЛОГО / WB RED (Слайдер + Тумблер) 
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Баланс белого"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            Switch {
                                text: "АВТО"
                                checked: cameraController.wbAuto
                                onCheckedChanged: cameraController.wbAuto = checked
                                Material.accent: Material.LightGreen
                            }
                        }
                        
                        RowLayout {
                            Layout.fillWidth: true
                            // Визуальное затухание текста, когда включен АВТО-режим
                            opacity: cameraController.wbAuto ? 0.4 : 1.0
                            Text { 
                                text: "Красный канал"
                                color: "#aaa"; font.pixelSize: 14
                                Layout.fillWidth: true
                            }
                            Text { 
                                text: cameraController.wbRedValue.toFixed(2)
                                color: cameraController.wbAuto ? "#aaa" : "#ff9100"
                                font.pixelSize: 16; font.bold: true 
                            }
                        }
                        
                        Slider {
                            Layout.fillWidth: true; Layout.preferredHeight: 32
                            from: 0.8; to: 3.0; value: cameraController.wbRedValue
                            // Блокировка слайдера при активном АВТО-режиме
                            enabled: !cameraController.wbAuto
                            onMoved: cameraController.wbRedValue = value
                        }
                    }

                    // ГАММА / GAMMA CONTRAST (Слайдер) 
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { 
                                text: "Гамма (Контраст)"
                                color: "white"; font.pixelSize: 16; font.bold: true
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            Text { 
                                text: cameraController.gammaValue.toFixed(2)
                                color: "#e040fb"; font.pixelSize: 16; font.bold: true 
                            }
                        }
                        Slider {
                            Layout.fillWidth: true; Layout.preferredHeight: 32
                            from: 0.5; to: 3.0; value: cameraController.gammaValue
                            onMoved: cameraController.gammaValue = value
                        }
                    }

                    Item { Layout.preferredHeight: 10 } 

                    // БЛОК КНОПОК ПРЕСЕТОВ (RESET / LOAD / SAVE) 
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

                    // ГЛАВНЫЕ ДЕЙСТВИЯ (СНИМОК / ВИДЕО) 
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        
                        Button {
                            text: "СНИМОК"
                            Layout.fillWidth: true; Layout.preferredHeight: 55
                            enabled: cameraController.status === "Камера запущена" || cameraController.isRecording
                            onClicked: fileDialog.open()
                            Material.background: Material.Blue
                        }
                        
                        Button {
                            // Тернарный оператор: меняет текст и цвет в зависимости от статуса записи
                            text: cameraController.isRecording ? "СТОП ЗАПИСЬ" : "ВИДЕО"
                            Layout.fillWidth: true; Layout.preferredHeight: 55
                            enabled: cameraController.status === "Камера запущена" || cameraController.isRecording
                            
                            onClicked: {
                                if (cameraController.isRecording) {
                                    cameraController.stop_video_recording()
                                } else {
                                    videoDialog.open()
                                }
                            }
                            Material.background: cameraController.isRecording ? Material.DeepOrange : Material.Purple
                        }
                    }

                    // УПРАВЛЕНИЕ ПОТОКОМ (СТАРТ / СТОП) 
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        Button {
                            text: "СТАРТ"; Layout.fillWidth: true; Layout.preferredHeight: 55
                            visible: cameraController.status !== "Камера запущена" && !cameraController.isRecording
                            onClicked: cameraController.start_camera()
                            Material.background: Material.Green
                        }
                        Button {
                            text: "СТОП"; Layout.fillWidth: true; Layout.preferredHeight: 55
                            visible: cameraController.status === "Камера запущена" || cameraController.isRecording
                            onClicked: cameraController.stop_camera()
                            Material.background: Material.Red
                        }
                    }

                    // БЛОК ТЕЛЕМЕТРИИ (FPS / РАЗРЕШЕНИЕ / ЭФФЕКТИВНОСТЬ) 
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
                                        // Индикация просадки кадров
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
                                    text: "TARGET / EFFICIENCY"; color: "#666"; font.pixelSize: 11; 
                                    font.bold: true; Layout.alignment: Qt.AlignRight;
                                    // Динамический перенос строк для длинных заголовков
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
    } /

    
    // === СИСТЕМНЫЕ ДИАЛОГОВЫЕ ОКНА ===    
    // Диалог сохранения фото (JPG / PNG)
    FileDialog {
        id: fileDialog
        title: "Сохранить кадр"
        fileMode: FileDialog.SaveFile
        nameFilters: ["JPEG Image (*.jpg)", "PNG Image (*.png)"]
        defaultSuffix: "jpg"
        currentFolder: StandardPaths.standardLocations(StandardPaths.PicturesLocation)[0]
        onAccepted: {
            var url = selectedFile.toString()
            var fmt = url.toLowerCase().endsWith(".png") ? "PNG" : "JPEG"
            cameraController.capture_photo(url, fmt, 95)
        }
    }

    // Диалог сохранения видео (MP4 / AVI)
    FileDialog {
        id: videoDialog
        title: "Сохранить видео"
        fileMode: FileDialog.SaveFile
        nameFilters: ["MP4 Video (*.mp4)", "AVI Video (*.avi)"]
        defaultSuffix: "mp4"
        currentFolder: StandardPaths.standardLocations(StandardPaths.MoviesLocation)[0]
        onAccepted: {
            var url = selectedFile.toString()
            var fmt = url.toLowerCase().endsWith(".avi") ? "avi" : "mp4"
            cameraController.start_video_recording(url, fmt)
        }
    }
}