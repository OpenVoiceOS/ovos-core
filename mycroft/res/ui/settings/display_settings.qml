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
import org.kde.plasma.core 2.0 as PlasmaCore
import Mycroft 1.0 as Mycroft
import OVOSPlugin 1.0 as OVOSPlugin
import QtGraphicalEffects 1.12

Item {
    id: displaySettingsView
    anchors.fill: parent
    property bool wallpaper_rotation_enabled: sessionData.display_wallpaper_rotation ? sessionData.display_wallpaper_rotation : 0
    property bool auto_dim_enabled: sessionData.display_auto_dim ? sessionData.display_auto_dim : 0
    property bool auto_nightmode_enabled: sessionData.display_auto_nightmode ? sessionData.display_auto_nightmode : 0

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
            text: qsTr("Display Settings")
            color: Kirigami.Theme.textColor
        }
    }

    Item {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top

        ColumnLayout {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Mycroft.Units.gridUnit / 2

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    id: displaySettingItemOneLabel
                    anchors.left: parent.left
                    anchors.right: autoWallpaperRotationSwitch.left
                    height: parent.height

                    Label {
                        id: settingOneLabel
                        text: qsTr("Wallpaper Rotation")
                        font.pixelSize: 25
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 15
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Changes the wallpaper automatically")
                        font.pixelSize: settingOneLabel.font.pixelSize / 2
                        color: Kirigami.Theme.textColor
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoWallpaperRotationSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    height: parent.height
                    checkable: true
                    checked: displaySettingsView.wallpaper_rotation_enabled
                    text: checked ? qsTr("ON") : qsTr("OFF")

                    Kirigami.Icon {
                        source: autoWallpaperRotationSwitch.checked ? Qt.resolvedUrl("images/switch-green.svg") : Qt.resolvedUrl("images/switch-red.svg")
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        height: Kirigami.Units.iconSizes.medium
                        width: Kirigami.Units.iconSizes.medium
                    }

                    onClicked: {
                        console.log(autoWallpaperRotationSwitch.checked)
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        triggerGuiEvent("speaker.extension.display.set.wallpaper.rotation", {"wallpaper_rotation": autoWallpaperRotationSwitch.checked})
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    id: displaySettingItemTwoLabel
                    anchors.left: parent.left
                    anchors.right: autoDimSwitch.left
                    height: parent.height

                    Label {
                        id: settingTwoLabel
                        text: qsTr("Auto Dim")
                        font.pixelSize: 25
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 15
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Dim's the display in 60 seconds")
                        font.pixelSize: settingTwoLabel.font.pixelSize / 2
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoDimSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    height: parent.height
                    checkable: true
                    checked: displaySettingsView.auto_dim_enabled
                    text: checked ? qsTr("ON") : qsTr("OFF")

                    Kirigami.Icon {
                        source: autoDimSwitch.checked ? Qt.resolvedUrl("images/switch-green.svg") : Qt.resolvedUrl("images/switch-red.svg")
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        height: Kirigami.Units.iconSizes.medium
                        width: Kirigami.Units.iconSizes.medium
                    }

                    onClicked: {
                        console.log(autoDimSwitch.checked)
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        triggerGuiEvent("speaker.extension.display.set.auto.dim", {"auto_dim": autoDimSwitch.checked})
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    id: displaySettingItemThreeLabel
                    anchors.left: parent.left
                    anchors.right: autoNightmodeSwitch.left
                    height: parent.height

                    Label {
                        id: settingThreeLabel
                        text: qsTr("Auto Nightmode")
                        font.pixelSize: 25
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 15
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Activates nightmode on homescreen, depending on the time of the day")
                        font.pixelSize: settingThreeLabel.font.pixelSize / 2
                        color: Kirigami.Theme.textColor
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoNightmodeSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    height: parent.height
                    checkable: true
                    checked: displaySettingsView.auto_nightmode_enabled
                    text: checked ? qsTr("ON") : qsTr("OFF")

                    Kirigami.Icon {
                        source: autoNightmodeSwitch.checked ? Qt.resolvedUrl("images/switch-green.svg") : Qt.resolvedUrl("images/switch-red.svg")
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        height: Kirigami.Units.iconSizes.medium
                        width: Kirigami.Units.iconSizes.medium
                    }

                    onClicked: {
                        console.log(autoNightmodeSwitch.checked)
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        triggerGuiEvent("speaker.extension.display.set.auto.nightmode", {"auto_nightmode": autoNightmodeSwitch.checked})
                    }
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
                triggerGuiEvent("mycroft.device.settings", {})
                Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
            }
        }
    }
}
