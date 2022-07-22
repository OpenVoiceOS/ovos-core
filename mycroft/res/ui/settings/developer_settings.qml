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
import QtQuick.Controls 2.0
import org.kde.kirigami 2.5 as Kirigami
import Mycroft 1.0 as Mycroft
import QtGraphicalEffects 1.12

Item {
    id: developerSettingsView
    anchors.fill: parent
    property bool dashActive: sessionData.dashboard_enabled ? Boolean(sessionData.dashboard_enabled) : false
    property bool busyVisible: false

    onDashActiveChanged: {
        developerSettingsView.busyVisible = false
    }

    Item {
        id: topArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Kirigami.Units.gridUnit * 2

        Kirigami.Heading {
            id: brightnessSettingPageTextHeading
            level: 1
            wrapMode: Text.WordWrap
            anchors.centerIn: parent
            font.bold: true
            text: qsTr("Developer Settings")
            color: Kirigami.Theme.textColor
        }
    }

    Item {
        id: viewBusyOverlay
        z: 300
        anchors.top: topArea.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top
        visible: developerSettingsView.busyVisible
        enabled: visible

        BusyIndicator {
            id: viewBusyIndicator
            visible: viewBusyOverlay.visible
            anchors.centerIn: parent
            running: viewBusyOverlay.visible
            enabled: viewBusyOverlay.visible
        }
    }

    Item {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: Kirigami.Units.smallSpacing

            Button {
                id: advancedSettingButton
                Layout.fillWidth: true
                Layout.preferredHeight: Mycroft.Units.gridUnit * 4

                background: Rectangle {
                    color: "transparent"
                }

                contentItem: RowLayout {
                    Image {
                        id: iconAdvancedSettingHolder
                        Layout.alignment: Qt.AlignVCenter | Qt.AlignLeft
                        Layout.preferredHeight: units.iconSizes.medium
                        Layout.preferredWidth: units.iconSizes.medium
                        source: "images/settings.png"

                        ColorOverlay {
                            anchors.fill: parent
                            source: iconSettingHolder
                            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.7)
                        }
                    }


                    Kirigami.Heading {
                        id: connectionNameLabel
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        height: paintedHeight
                        elide: Text.ElideRight
                        font.weight: Font.DemiBold
                        text: qsTr("Advanced Settings")
                        textFormat: Text.PlainText
                        color: Kirigami.Theme.textColor
                        level: 2
                    }
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("ovos.phal.configuration.provider.list.groups", {})
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
            }

            Kirigami.Heading {
                id: warnText
                level: 3
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.textColor
                text: "Enabling OVOS Dashboard will provide you access to control various services on this device, the OVOS Dashboard can be accessed on any device located in your LAN network"
            }

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.largeSpacing
            }

            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                text: qsTr("Enable Dashboard")
                visible: !dashActive
                enabled: visible
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    triggerGuiEvent("mycroft.device.enable.dash", {})
                    developerSettingsView.busyVisible = true
                }
            }

            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                text: qsTr("Disable Dashboard")
                visible: dashActive
                enabled: visible
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    triggerGuiEvent("mycroft.device.disable.dash", {})
                    developerSettingsView.busyVisible = true
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                visible: dashActive
                enabled: visible
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                level: 3
                color: Kirigami.Theme.textColor
                text: qsTr("Dashboard Address") + ": " +  sessionData.dashboard_url
                visible: dashActive
                enabled: visible
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                level: 3
                color: Kirigami.Theme.textColor
                text: qsTr("Dashboard Username")+ ": " + sessionData.dashboard_user
                visible: dashActive
                enabled: visible
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                level: 3
                color: Kirigami.Theme.textColor
                text: qsTr("Dashboard Password") + ": " + sessionData.dashboard_password
                visible: dashActive
                enabled: visible
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
