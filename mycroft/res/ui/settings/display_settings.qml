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
    property bool wallpaper_rotation_enabled: false
    property bool auto_dim_enabled: sessionData.display_auto_dim ? sessionData.display_auto_dim : 0
    property bool auto_nightmode_enabled: sessionData.display_auto_nightmode ? sessionData.display_auto_nightmode : 0
    property bool menuLabelsEnabled: false

    function getAutoRotation() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.auto.rotation", {})
    }

    Component.onCompleted: {
        getAutoRotation()
        Mycroft.MycroftController.sendRequest("ovos.shell.get.menuLabels.status", {})
    }

    Connections {
        target: Mycroft.MycroftController
        onIntentRecevied: {
            if (type == "ovos.shell.get.menuLabels.status.response") {
                menuLabelsEnabled = data.enabled
            }
            if (type == "ovos.wallpaper.manager.get.auto.rotation.response") {
                wallpaper_rotation_enabled = data.auto_rotation
            }
        }
    }

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

    ScrollBar {
        id: flickAreaScrollBar
        anchors.right: parent.right
        width: Mycroft.Units.gridUnit
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.bottom: bottomArea.top
    }

    Flickable {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: flickAreaScrollBar.left
        anchors.bottom: midBottomArea.top
        contentWidth: width
        contentHeight: mainColLayoutDisplaySettings.implicitHeight
        ScrollBar.vertical: flickAreaScrollBar
        clip: true

        ColumnLayout {
            id: mainColLayoutDisplaySettings
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Mycroft.Units.gridUnit / 2

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: displaySettingItemOneLabel.implicitHeight + Mycroft.Units.gridUnit
                color: Qt.lighter(Kirigami.Theme.backgroundColor, 2)
                border.width: 1
                border.color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                radius: 6

                ColumnLayout {
                    id: displaySettingItemOneLabel
                    anchors.left: parent.left
                    anchors.right: autoWallpaperRotationSwitch.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Mycroft.Units.gridUnit / 2

                    Label {
                        id: settingOneLabel
                        text: qsTr("Wallpaper Rotation")
                        font.pixelSize: 18
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 14
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Changes the wallpaper automatically")
                        font.pixelSize: settingOneLabel.font.pixelSize / 1.5
                        color: Kirigami.Theme.textColor
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoWallpaperRotationSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    anchors.rightMargin: Mycroft.Units.gridUnit / 2
                    height: parent.height - Mycroft.Units.gridUnit / 2
                    anchors.verticalCenter: parent.verticalCenter
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

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: displaySettingItemTwoLabel.implicitHeight + Mycroft.Units.gridUnit
                color: Qt.lighter(Kirigami.Theme.backgroundColor, 2)
                border.width: 1
                border.color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                radius: 6

                ColumnLayout {
                    id: displaySettingItemTwoLabel
                    anchors.left: parent.left
                    anchors.right: autoDimSwitch.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Mycroft.Units.gridUnit / 2

                    Label {
                        id: settingTwoLabel
                        text: qsTr("Auto Dim")
                        font.pixelSize: 18
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 14
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Dim's the display in 60 seconds")
                        font.pixelSize: settingTwoLabel.font.pixelSize / 1.5
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                        color: Kirigami.Theme.textColor
                        maximumLineCount: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoDimSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    anchors.rightMargin: Mycroft.Units.gridUnit / 2
                    height: parent.height - Mycroft.Units.gridUnit / 2
                    anchors.verticalCenter: parent.verticalCenter
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

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: displaySettingItemThreeLabel.implicitHeight + Mycroft.Units.gridUnit
                color: Qt.lighter(Kirigami.Theme.backgroundColor, 2)
                border.width: 1
                border.color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                radius: 6

                ColumnLayout {
                    id: displaySettingItemThreeLabel
                    anchors.left: parent.left
                    anchors.right: autoNightmodeSwitch.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Mycroft.Units.gridUnit / 2

                    Label {
                        id: settingThreeLabel
                        text: qsTr("Auto Nightmode")
                        font.pixelSize: 18
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 14
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Activates nightmode on homescreen, depending on the time of the day")
                        font.pixelSize: settingThreeLabel.font.pixelSize / 1.5
                        color: Kirigami.Theme.textColor
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        maximumLineCount: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: autoNightmodeSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    anchors.rightMargin: Mycroft.Units.gridUnit / 2
                    height: parent.height - Mycroft.Units.gridUnit / 2
                    anchors.verticalCenter: parent.verticalCenter
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

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: displaySettingItemFourLabel.implicitHeight + Mycroft.Units.gridUnit
                color: Qt.lighter(Kirigami.Theme.backgroundColor, 2)
                border.width: 1
                border.color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                radius: 6

                ColumnLayout {
                    id: displaySettingItemFourLabel
                    anchors.left: parent.left
                    anchors.right: displayMenuLabelsSwitch.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Mycroft.Units.gridUnit / 2

                    Label {
                        id: settingFourLabel
                        text: qsTr("Display Menu Labels")
                        font.pixelSize: 18
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 14
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }

                    Label {
                        text: qsTr("Enable|Disable display of menu labels")
                        font.pixelSize: settingFourLabel.font.pixelSize / 1.5
                        color: Kirigami.Theme.textColor
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        maximumLineCount: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.alignment: Qt.AlignLeft
                    }
                }

                Button {
                    id: displayMenuLabelsSwitch
                    width: Mycroft.Units.gridUnit * 10
                    anchors.right: parent.right
                    anchors.rightMargin: Mycroft.Units.gridUnit / 2
                    height: parent.height - Mycroft.Units.gridUnit / 2
                    anchors.verticalCenter: parent.verticalCenter
                    checkable: true
                    checked: displaySettingsView.menuLabelsEnabled
                    text: checked ? qsTr("ON") : qsTr("OFF")

                    Kirigami.Icon {
                        source: displayMenuLabelsSwitch.checked ? Qt.resolvedUrl("images/switch-green.svg") : Qt.resolvedUrl("images/switch-red.svg")
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        height: Kirigami.Units.iconSizes.medium
                        width: Kirigami.Units.iconSizes.medium
                    }

                    onClicked: {
                        console.log(displayMenuLabelsSwitch.checked)
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        Mycroft.MycroftController.sendRequest("ovos.shell.set.menuLabels", {"enabled": displayMenuLabelsSwitch.checked})
                    }
                }
            }
        }
    }

    Item {
        id: midBottomArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top
        height: Math.max(Mycroft.Units.gridUnit * 5, Kirigami.Units.iconSizes.large)

        Kirigami.Separator {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1
        }

        Button {
            id: wallpaperSettingButton
            width: parent.width
            height: Math.max(Mycroft.Units.gridUnit * 5, Kirigami.Units.iconSizes.large)

            background: Rectangle {
                id: wallpaperSettingButtonBg
                color: "transparent"
            }

            contentItem: RowLayout {
                Image {
                    id: iconWallpaperSettingHolder
                    Layout.alignment: Qt.AlignVCenter | Qt.AlignLeft
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    source: "images/settings.png"

                    ColorOverlay {
                        anchors.fill: parent
                        source: iconWallpaperSettingHolder
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
                    text: "Wallpaper Settings"
                    textFormat: Text.PlainText
                    color: Kirigami.Theme.textColor
                    level: 2
                }
            }

            onClicked: {
                Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                console.log("Sending Show Wallpaper Page Here")
                triggerGuiEvent("mycroft.device.settings.wallpapers", {})
            }

            onPressed: {
                wallpaperSettingButtonBg.color = Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.4)
            }
            onReleased: {
                wallpaperSettingButtonBg.color = "transparent"
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
