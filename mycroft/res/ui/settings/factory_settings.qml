/*
 * Copyright 2022 Aditya Mehra <aix.m@outlook.com>
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
import QtQuick 2.12
import QtQuick.Controls 2.11
import org.kde.kirigami 2.11 as Kirigami
import Mycroft 1.0 as Mycroft
import OVOSPlugin 1.0 as OVOSPlugin
import QtGraphicalEffects 1.0

Item {
    id: factorySettingsView
    anchors.fill: parent
    property bool horizontalMode: width > height ? 1 :0

    Item {
        id: topArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Kirigami.Units.gridUnit * 2

        Kirigami.Heading {
            id: idleSettingPageTextHeading
            level: 1
            wrapMode: Text.WordWrap
            anchors.centerIn: parent
            font.bold: true
            text: qsTr("Factory Reset Settings")
            color: Kirigami.Theme.textColor
        }
    }

    Flickable {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top
        contentWidth: width
        contentHeight: factorySettingsLayout.implicitHeight
        ScrollBar.vertical: ScrollBar {
            width: Mycroft.Units.gridUnit
            anchors.right: parent.right
        }
        clip: true

        GridLayout {
            id: factorySettingsLayout
            width: parent.width - Mycroft.Units.gridUnit * 2
            anchors.horizontalCenter: parent.horizontalCenter
            columns: horizontalMode ? 2 : 1
            columnSpacing: Mycroft.Units.gridUnit / 2
            rowSpacing: Mycroft.Units.gridUnit / 2

            Button {
                text: qsTr("Wipe Cache")
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                
                background: Rectangle {
                    Kirigami.Theme.inherit: false
                    Kirigami.Theme.colorSet: Kirigami.Theme.Button
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    radius: 6
                }

                contentItem: Label {
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Wipe Cache")
                    color: Kirigami.Theme.textColor
                }
                
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("system.factory.reset", {"wipe_cache": true, "wipe_data": false, "wipe_logs": false, "wipe_config": false, "reset_hardware": false})
                }

                onPressed: {
                    opacity = 0.5
                }
                onReleased: {
                    opacity = 1
                }
            }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4

                background: Rectangle {
                    Kirigami.Theme.inherit: false
                    Kirigami.Theme.colorSet: Kirigami.Theme.Button
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    radius: 6
                }

                contentItem: Label {
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Wipe Config")
                    color: Kirigami.Theme.textColor
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("system.factory.reset", {"wipe_cache": false, "wipe_data": false, "wipe_logs": false, "wipe_config": true, "reset_hardware": false})
                }

                onPressed: {
                    opacity = 0.5
                }
                onReleased: {
                    opacity = 1
                }
            }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4


                background: Rectangle {
                    Kirigami.Theme.inherit: false
                    Kirigami.Theme.colorSet: Kirigami.Theme.Button
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    radius: 6
                }

                contentItem: Label {
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Wipe Data")
                    color: Kirigami.Theme.textColor
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("system.factory.reset", {"wipe_cache": false, "wipe_data": true, "wipe_logs": false, "wipe_config": false, "reset_hardware": false})
                }

                onPressed: {
                    opacity = 0.5
                }
                onReleased: {
                    opacity = 1
                }
            }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4

                background: Rectangle {
                    Kirigami.Theme.inherit: false
                    Kirigami.Theme.colorSet: Kirigami.Theme.Button
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    radius: 6
                }

                contentItem: Label {
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Wipe Logs")
                    color: Kirigami.Theme.textColor
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("system.factory.reset", {"wipe_cache": false, "wipe_data": false, "wipe_logs": true, "wipe_config": false, "reset_hardware": false})
                }

                onPressed: {
                    opacity = 0.5
                }
                onReleased: {
                    opacity = 1
                }
            }

            Button {
                id: factoryResetButton
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4

                background: Rectangle {
                    Kirigami.Theme.inherit: false
                    Kirigami.Theme.colorSet: Kirigami.Theme.Button
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                    radius: 6
                }

                contentItem: Label {
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Factory Reset")
                    color: Kirigami.Theme.textColor
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("system.factory.reset", {"wipe_cache": true, "wipe_data": true, "wipe_logs": true, "wipe_config": true, "reset_hardware": true})
                }

                onPressed: {
                    opacity = 0.5
                }
                onReleased: {
                    opacity = 1
                }
            }
        }
    }

    Item {
        id: bottomArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Mycroft.Units.gridUnit * 6

        Kirigami.Separator {
            id: areaSep
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            color: Kirigami.Theme.highlightColor
            height: 2
        }

        RowLayout {
            anchors.fill: parent

            Kirigami.Icon {
                id: backIcon
                source: Qt.resolvedUrl("images/back.svg")
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium

                ColorOverlay {
                    anchors.fill: parent
                    source: backIcon
                    color: Kirigami.Theme.textColor
                }
            }

            Kirigami.Heading {
                level: 2
                wrapMode: Text.WordWrap
                font.bold: true
                text: qsTr("Device Settings")
                color: Kirigami.Theme.textColor
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2
            }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: {
                Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                triggerGuiEvent("mycroft.device.settings", {})
            }
        }
    }
}
