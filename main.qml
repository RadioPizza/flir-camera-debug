import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    title: "FLIR Camera Tool - Sony IMX429"
    visible: true
    
    // Открыть на весь экран
    Component.onCompleted: {
        window.showMaximized()
    }

    Rectangle {
        anchors.fill: parent
        color: "#070707ff"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 10

            // Заголовок
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 40

                Label {
                    text: "FLIR Camera Tool - Sony IMX429"
                    font.pixelSize: 20
                    font.bold: true
                    color: "#1A202C"
                    Layout.fillWidth: true
                }

                // Статус камеры
                Rectangle {
                    width: statusText.width + 20
                    height: 28
                    color: cameraController.status.includes("Ошибка") ? "#ff4444" : 
                           cameraController.status.includes("запущена") ? "#44ff44" : "#888888"
                    radius: 14

                    Label {
                        id: statusText
                        anchors.centerIn: parent
                        text: cameraController.status
                        font.pixelSize: 12
                        font.bold: true
                        color: "white"
                    }
                }
            }

            // Основное содержимое
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 20

                // Область предпросмотра камеры
                Rectangle {
                    Layout.fillHeight: true
                    Layout.preferredWidth: parent.width * 0.45
                    Layout.maximumWidth: parent.width * 0.5
                    border.color: "#555555"
                    border.width: 2
                    radius: 8
                    color: "#1a1a1a"

                    // Изображение с камеры
                    Image {
                        id: cameraImage
                        anchors.fill: parent
                        anchors.margins: 2
                        source: cameraController.frameData
                        fillMode: Image.PreserveAspectFit
                        cache: false
                        asynchronous: true
                        smooth: false
                    }

                    // Индикатор загрузки
                    BusyIndicator {
                        anchors.centerIn: parent
                        running: cameraController.status === "Камера запущена" && 
                                cameraController.frameData === ""
                        visible: running
                    }

                    // Сообщение когда камера не запущена
                    Label {
                        anchors.centerIn: parent
                        text: "Нажмите 'Запустить камеру' для начала работы"
                        color: "#888888"
                        font.pixelSize: 16
                        visible: cameraController.status !== "Камера запущена" && 
                                !cameraController.status.includes("Ошибка") &&
                                cameraController.frameData === ""
                    }
                }

                // Правая панель
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 15

                    // Информация о камере (расширенная)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredHeight: 200
                        color: "#3a3a3a"
                        radius: 8

                        GridLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            columns: 2
                            rowSpacing: 10
                            columnSpacing: 15

                            Label {
                                text: "Найдено камер:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: cameraController.cameraInfo.cameras_found || "0"
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "Разрешение:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: cameraController.cameraInfo.resolution || "1936×1464"
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "Формат:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: cameraController.cameraInfo.pixel_format || "Неизвестно"
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "FPS:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: Math.round(cameraController.currentFps * 10) / 10
                                color: cameraController.currentFps > 30 ? "#44ff44" : 
                                       cameraController.currentFps > 15 ? "#ffff44" : "#ff4444"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "Усиление:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: cameraController.cameraInfo.gain || "15.0 dB"
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "Гамма:"
                                color: "#aaaaaa"
                                font.pixelSize: 14
                            }
                            Label {
                                text: cameraController.cameraInfo.gamma || "0.7"
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                                Layout.fillWidth: true
                            }
                        }
                    }

                    // Управление камерой (крупные кнопки)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredHeight: 200
                        color: "#3a3a3a"
                        radius: 8

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 15

                            // Кнопка остановки
                            Button {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.preferredWidth: 0
                                enabled: cameraController.status.includes("запущена")
                                onClicked: cameraController.stop_camera()

                                background: Rectangle {
                                    color: parent.enabled ? "#ff4444" : "#555555"
                                    radius: 8
                                    border.width: 3
                                    border.color: parent.enabled ? "#cc3333" : "#444444"
                                }

                                contentItem: Text {
                                    text: "■\nОСТАНОВИТЬ"
                                    font.pixelSize: 28
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "white"
                                }
                            }

                            // Кнопка запуска
                            Button {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.preferredWidth: 0
                                enabled: !cameraController.status.includes("запущена") && 
                                        !cameraController.status.includes("Ошибка")
                                onClicked: cameraController.start_camera()

                                background: Rectangle {
                                    color: parent.enabled ? "#44ff44" : "#555555"
                                    radius: 8
                                    border.width: 3
                                    border.color: parent.enabled ? "#33cc33" : "#444444"
                                }

                                contentItem: Text {
                                    text: "▶\nЗАПУСТИТЬ"
                                    font.pixelSize: 28
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "white"
                                }
                            }

                            // Кнопка снимка
                            Button {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.preferredWidth: 0
                                enabled: cameraController.status.includes("запущена")
                                onClicked: photoDialog.open()

                                background: Rectangle {
                                    color: parent.enabled ? "#4444ff" : "#555555"
                                    radius: 8
                                    border.width: 3
                                    border.color: parent.enabled ? "#3333cc" : "#444444"
                                }

                                contentItem: Text {
                                    text: "📸\nСНИМОК"
                                    font.pixelSize: 28
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "white"
                                }
                            }
                        }
                    }

                    // Настройки сохранения
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredHeight: 150
                        color: "#3a3a3a"
                        radius: 8

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            Label {
                                text: "НАСТРОЙКИ СОХРАНЕНИЯ"
                                font.pixelSize: 16
                                font.bold: true
                                color: "white"
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                
                                Label {
                                    text: "Формат:"
                                    color: "white"
                                    font.pixelSize: 14
                                    font.bold: true
                                    Layout.preferredWidth: 70
                                }
                                
                                ComboBox {
                                    id: photoFormatCombo
                                    model: ["PNG", "JPEG"]
                                    currentIndex: 0
                                    Layout.fillWidth: true
                                    font.pixelSize: 14
                                    
                                    background: Rectangle {
                                        color: "#555555"
                                        radius: 6
                                        border.width: 1
                                        border.color: "#666666"
                                    }
                                    
                                    contentItem: Text {
                                        text: photoFormatCombo.currentText
                                        color: "white"
                                        font.pixelSize: 14
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    
                                    popup: Popup {
                                        width: photoFormatCombo.width
                                        implicitHeight: contentItem.implicitHeight
                                        padding: 5
                                        
                                        contentItem: ListView {
                                            clip: true
                                            implicitHeight: contentHeight
                                            model: photoFormatCombo.popup.visible ? photoFormatCombo.delegateModel : null
                                            currentIndex: photoFormatCombo.highlightedIndex
                                            
                                            ScrollIndicator.vertical: ScrollIndicator { }
                                        }
                                        
                                        background: Rectangle {
                                            color: "#3a3a3a"
                                            radius: 6
                                            border.width: 1
                                            border.color: "#666666"
                                        }
                                    }
                                }
                            }
                            
                            RowLayout {
                                Layout.fillWidth: true
                                
                                Label {
                                    text: "Качество:"
                                    color: "white"
                                    font.pixelSize: 14
                                    font.bold: true
                                    Layout.preferredWidth: 70
                                }
                                
                                Slider {
                                    id: qualitySlider
                                    Layout.fillWidth: true
                                    from: 1
                                    to: 100
                                    value: 95
                                    onValueChanged: cameraController.set_photo_quality(value)
                                    
                                    background: Rectangle {
                                        implicitHeight: 8
                                        color: "#555555"
                                        radius: 4
                                        
                                        Rectangle {
                                            width: qualitySlider.visualPosition * parent.width
                                            height: parent.height
                                            color: "#44ff44"
                                            radius: 4
                                        }
                                    }
                                    
                                    handle: Rectangle {
                                        x: qualitySlider.visualPosition * (qualitySlider.width - width)
                                        y: qualitySlider.height / 2 - height / 2
                                        implicitWidth: 20
                                        implicitHeight: 20
                                        radius: 10
                                        color: qualitySlider.pressed ? "#ffffff" : "#cccccc"
                                        border.width: 2
                                        border.color: "#44ff44"
                                    }
                                }
                                
                                Label {
                                    text: qualitySlider.value + "%"
                                    color: "white"
                                    font.pixelSize: 14
                                    font.bold: true
                                    Layout.preferredWidth: 50
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Диалог сохранения фото
    Dialog {
        id: photoDialog
        title: "Сохранить снимок"
        standardButtons: Dialog.Save | Dialog.Cancel
        anchors.centerIn: parent
        modal: true
        width: 400
        height: 200

        background: Rectangle {
            color: "#3a3a3a"
            radius: 8
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 15
            spacing: 12

            Label {
                text: "Снимок готов к сохранению"
                color: "white"
                font.pixelSize: 16
                font.bold: true
            }

            TextField {
                id: photoFileNameField
                placeholderText: "Введите имя файла"
                text: "flir_photo_" + new Date().toISOString().slice(0,19).replace(/:/g,'-')
                Layout.fillWidth: true
                font.pixelSize: 14
                
                background: Rectangle {
                    color: "#555555"
                    radius: 4
                    border.width: 1
                    border.color: "#666666"
                }
            }

            Label {
                text: "Формат: " + photoFormatCombo.currentText + " | Качество: " + qualitySlider.value + "%"
                color: "#aaaaaa"
                font.pixelSize: 12
            }
        }

        onAccepted: {
            var filePath = photoFileNameField.text
            var format = photoFormatCombo.currentText
            var quality = qualitySlider.value
            cameraController.capture_photo(filePath, format, quality)
        }
    }

    // Статус бар
    footer: Rectangle {
        height: 30
        color: "#1a1a1a"

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10

            Label {
                text: "FLIR Camera Tool v4.0 - Sony IMX429"
                color: "gray"
                font.pixelSize: 12
            }

            Item { Layout.fillWidth: true }

            Label {
                text: "Для выхода нажмите Q в консоли | Esc: оконный режим"
                color: "#ff4444"
                font.pixelSize: 12
            }
        }
    }

    // Горячие клавиши
    Shortcut {
        sequence: "Esc"
        onActivated: {
            if (window.visibility === Window.FullScreen) {
                window.showNormal()
            } else {
                window.showFullScreen()
            }
        }
    }
}