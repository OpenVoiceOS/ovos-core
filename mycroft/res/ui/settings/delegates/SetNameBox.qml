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

Popup  {
    id: nameSelectBox
    width: parent.width * 0.75
    height: parent.height * 0.75
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    dim: true
    property string nameValue

    onNameValueChanged: {
        if(nameValue != "" && nameValue.length > 2 || nameValue != "  " && nameValue.length > 2) {
            createThemeView.selectedThemeName = nameValue[0].toUpperCase() + nameValue.slice(1) + " Scheme"
        } else {
            createThemeView.selectedThemeName = qsTr("Example Theme")
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
                text: qsTr("Set Scheme Name")
                color: Kirigami.Theme.textColor
                elide: Text.ElideRight
            }
        }

        TextField {
            id: popupMainContent
            anchors.top: popupHeaderArea.bottom
            anchors.bottom: popupBottomArea.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Mycroft.Units.gridUnit / 2

            background: Rectangle {
                color: Kirigami.Theme.backgroundColor
                border.width: 1
                border.color: Kirigami.Theme.textColor
                radius: 6

                Label {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit / 2
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    visible: popupMainContent.activeFocus ? 0 : 1
                    text: qsTr("Unique 1 word scheme name, example: Midnight")
                    color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    wrapMode: Text.WordWrap
                }
            }
            palette.text: Kirigami.Theme.textColor
            validator: RegExpValidator { regExp: /^([A-z])*[^\s]\1*$/ }
            onTextChanged: {
                nameSelectBox.nameValue = popupMainContent.text
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
                    nameSelectBox.close()
                }
            }
        }
    }
}

