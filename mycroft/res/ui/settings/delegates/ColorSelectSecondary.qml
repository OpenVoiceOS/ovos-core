/*
 * Copyright 2018 Aditya Mehra <aix.m@outlook.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */

import QtQuick.Layouts 1.4
import QtQuick 2.4
import QtQuick.Controls 2.11
import org.kde.kirigami 2.11 as Kirigami
import Mycroft 1.0 as Mycroft
import OVOSPlugin 1.0 as OVOSPlugin
import QtGraphicalEffects 1.12
import "../code/colorUtils.js" as ColorUtils

Popup  {
    id: colorSelectSecondaryBox
    width: parent.width * 0.9
    height: parent.height * 0.9
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    dim: true
    property color colorValue: Kirigami.Theme.highlightColor
    property bool darkHue: false
    property color _changingColorValue : ColorUtils._hsla(hueSlider.value, 1, 1, 1)
    property color _tempColorValue: "transparent"
    property var brightnessSliderValue: brightnessSlider.value

    onColorValueChanged: {
        createThemeView.selectedSecondaryColor = colorValue
    }

    on_ChangingColorValueChanged: {
        _tempColorValue = _changingColorValue
    }

    onBrightnessSliderValueChanged: {
        if(brightnessSliderValue >= 1) {
            darkHue: true
        } else {
            darkHue: false
        }
    }

    Overlay.modeless: Rectangle {
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
    }

    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
        layer.enabled: true
        layer.effect: DropShadow {
            color: Kirigami.Theme.backgroundColor
            transparentBorder: false
            horizontalOffset: 0
            verticalOffset: 0
            spread: 0.2
            radius: 8
            samples: 16
        }

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.1)
        }
    }

    contentItem: Item {

        Rectangle {
            id: popupHeaderArea
            color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.6)
            anchors.left: parent.left
            anchors.right: parent.right
            height: Mycroft.Units.gridUnit * 5
            radius: 4

            Label {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: Mycroft.Units.gridUnit / 2
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: 32
                font.bold: true
                minimumPixelSize: 5
                fontSizeMode: Text.Fit
                maximumLineCount: 1
                text: "Select Secondary Color"
                color: Kirigami.Theme.textColor
                elide: Text.ElideRight
            }
        }

        Item {
            anchors.top: popupHeaderArea.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: popupBottomArea.top
            anchors.margins: Mycroft.Units.gridUnit / 2

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10

                Rectangle {
                    Layout.preferredWidth: parent.width / 2
                    Layout.fillHeight: true
                    color: darkHue ? Qt.lighter(_tempColorValue, brightnessSliderValue) : Qt.darker(_tempColorValue, brightnessSliderValue)

                    onColorChanged: {
                        colorValue = color
                    }
                }

                Item {
                    id: huePicker
                    Layout.preferredWidth: Mycroft.Units.gridUnit * 2
                    Layout.fillHeight: true
                    Layout.topMargin: 8
                    Layout.bottomMargin: 8

                    Rectangle {
                        anchors.fill: parent
                        id: colorBar
                        gradient: Gradient {
                            GradientStop { position: 1.0;  color: "#FF0000" }
                            GradientStop { position: 0.85; color: "#FFFF00" }
                            GradientStop { position: 0.76; color: "#00FF00" }
                            GradientStop { position: 0.5;  color: "#00FFFF" }
                            GradientStop { position: 0.33; color: "#0000FF" }
                            GradientStop { position: 0.16; color: "#FF00FF" }
                            GradientStop { position: 0.0;  color: "#FF0000" }
                        }
                    }
                    ColorSlider {
                        id: hueSlider; anchors.fill: parent
                    }
                }

                BrightnessSlider {
                    id: brightnessSlider
                    Layout.fillHeight: true
                    Layout.preferredWidth: Mycroft.Units.gridUnit * 2
                }
            }
        }

        Rectangle {
            id: popupBottomArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Mycroft.Units.gridUnit * 5
            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.1)
            border.color: Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.5)
            border.width: 1
            radius: 4

            RowLayout {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.margins: Mycroft.Units.gridUnit / 2

                Kirigami.Icon {
                    id: backIconPopUp
                    source: "window-close-symbolic"
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium

                    ColorOverlay {
                        anchors.fill: parent
                        source: backIconPopUp
                        color: Kirigami.Theme.textColor
                    }
                }

                Kirigami.Heading {
                    level: 2
                    wrapMode: Text.WordWrap
                    font.bold: true
                    color: Kirigami.Theme.textColor
                    text: "Close"
                    verticalAlignment: Text.AlignVCenter
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../../snd/clicked.wav"))
                    colorSelectSecondaryBox.close()
                }
            }
        }
    }
}

