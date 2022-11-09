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

ItemDelegate {
    id: themeViewer
    property bool darkMode: false
    property var modelDataStyle: darkMode ? "dark" : "light"
    property color viewPrimaryColor
    property color viewSecondaryColor
    property color viewTextColor
    property string themeName
    property bool clickEnabled: true

    background: Rectangle {
        color: darkMode ? themeViewer.viewPrimaryColor : themeViewer.viewTextColor
        border.color: themeViewer.viewSecondaryColor
        border.width: 3
        radius: 10
    }

    Item {
        id: d1itemThemeView
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Mycroft.Units.gridUnit / 2
        height: parent.height * 0.70

        GridLayout {
            anchors.fill: parent
            anchors.margins: Mycroft.Units.gridUnit / 2
            columns: 2

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: darkMode ? themeViewer.viewPrimaryColor : themeViewer.viewTextColor
                border.width: 2
                border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.5)

                Text {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "P"
                    fontSizeMode: Text.Fit
                    minimumPixelSize: 5
                    font.pixelSize: 40
                    color: darkMode ? themeViewer.viewTextColor : themeViewer.viewPrimaryColor
                    font.bold: true
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: themeViewer.viewSecondaryColor
                border.width: 2
                border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.5)

                Text {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "S"
                    fontSizeMode: Text.Fit
                    minimumPixelSize: 5
                    font.pixelSize: 40
                    color: darkMode ? themeViewer.viewTextColor : themeViewer.viewPrimaryColor
                    font.bold: true
                }
            }
            Rectangle{
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: darkMode ? themeViewer.viewTextColor : themeViewer.viewPrimaryColor
                border.width: 2
                border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.5)

                Text {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "T"
                    fontSizeMode: Text.Fit
                    minimumPixelSize: 5
                    font.pixelSize: 40
                    color: darkMode ? themeViewer.viewPrimaryColor : themeViewer.viewTextColor
                    font.bold: true
                }
            }
            Rectangle{
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 15
                color: themeViewer.viewSecondaryColor
                border.width: 2
                border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.5)

                Rectangle {
                    color: darkMode ? themeViewer.viewPrimaryColor : themeViewer.viewTextColor
                    anchors.centerIn: parent
                    width: parent.width - 4
                    height: parent.height / 4

                    Label {
                        anchors.centerIn: parent
                        fontSizeMode: Text.HorizontalFit
                        font.pixelSize: 32
                        minimumPixelSize: 4
                        font.bold: true
                        color: darkMode ? themeViewer.viewTextColor : themeViewer.viewPrimaryColor
                        text: darkMode ? "Style 1" : "Style 2"
                    }
                }
            }
        }
    }

    Kirigami.Separator {
        id: cardSeptThemeView
        anchors.top: d1itemThemeView.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        height: 16
        color: themeViewer.viewSecondaryColor
    }

    Item {
        id: d2itemThemeView
        anchors.top: cardSeptThemeView.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true

        Label {
            anchors.fill: parent
            anchors.margins: Mycroft.Units.gridUnit / 2
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 20
            minimumPixelSize: 5
            fontSizeMode: Text.Fit
            maximumLineCount: 1
            text: themeViewer.themeName
            color: darkMode ? themeViewer.viewTextColor : themeViewer.viewPrimaryColor
            elide: Text.ElideRight
        }
    }

    onClicked: {
        if(clickEnabled){
            Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
            styleViewPopUp.setTheme(modelDataStyle)
            styleViewPopUp.close()
            Mycroft.MycroftController.sendRequest("ovos.theme.get", {})
        }
    }
}
