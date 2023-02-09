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
import "code/colorUtils.js" as ColorUtils
import "delegates" as Delegates

Item {
    id: createThemeView
    anchors.fill: parent
    property color selectedPrimaryColor: Kirigami.Theme.backgroundColor
    property color selectedSecondaryColor: Kirigami.Theme.highlightColor
    property color selectedTextColor: Kirigami.Theme.textColor
    property string selectedThemeName: qsTr("Example Scheme")

    onSelectedPrimaryColorChanged: {
        selectedTextColor = ColorUtils.autoTextColor(selectedPrimaryColor.r, selectedPrimaryColor.g, selectedPrimaryColor.b)
    }

    Connections {
        target: Mycroft.MycroftController

        onIntentRecevied: {
            if (type == "ovos.shell.gui.color.scheme.generated") {
                timeoutMessageTimer.stop()
                visualBusyIndicatorBox.visible = false
                visualBusyIndicatorBox.enabled = false
                // Go back to customize screen if there is a response
                triggerGuiEvent("mycroft.device.settings.customize", {})
            }
        }
    }

    // Wait sometime before closing the busy BusyIndicator
    // If there is no response from the phal plugin
    Timer {
        id: timeoutMessageTimer
        running: false
        interval: 12000
        repeat: false
        onTriggered: {
            if(visualBusyIndicatorBox.visible) {
                visualBusyIndicatorBox.visible = false
                visualBusyIndicatorBox.enabled = false
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
            id: customizeSettingPageTextHeading
            level: 1
            wrapMode: Text.WordWrap
            anchors.centerIn: parent
            font.bold: true
            text: qsTr("Create Scheme")
            color: Kirigami.Theme.textColor
        }
    }

    Item {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top

        Item {
            id: themeSetterArea
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: themePreviewArea.top

            GridLayout {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: themeSetterAreaBottomLine.top
                anchors.margins: Mycroft.Units.gridUnit / 2
                columns: 2
                rows: 2

                Rectangle {
                    id: primaryColorSelectButton
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.5)
                    border.color: Kirigami.Theme.highlightColor
                    border.width: 1

                    Rectangle {
                        id: buttonPrimaryColorPreviewBox
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: Mycroft.Units.gridUnit / 2
                        color: createThemeView.selectedPrimaryColor
                        width: height
                    }

                    Label {
                        anchors.left: buttonPrimaryColorPreviewBox.right
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 5
                        font.pixelSize: 24
                        font.bold: true
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        text: qsTr("Select Primary Color")
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                            primaryColorSelectorPopup.open()
                        }
                    }
                }
                Rectangle {
                    id: secondaryColorSelectButton
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.5)
                    border.color: Kirigami.Theme.highlightColor
                    border.width: 1

                    Rectangle {
                        id: buttonSecondaryColorPreviewBox
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: Mycroft.Units.gridUnit / 2
                        color: createThemeView.selectedSecondaryColor
                        width: height
                    }

                    Label {
                        anchors.left: buttonSecondaryColorPreviewBox.right
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 5
                        font.pixelSize: 24
                        font.bold: true
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        text: qsTr("Select Secondary Color")
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                            secondaryColorSelectorPopup.open()
                        }
                    }
                }
                Rectangle {
                    id: autoTextColorButton
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.5)
                    border.color: Kirigami.Theme.highlightColor
                    border.width: 1

                    Rectangle {
                        id: buttonTextColorPreviewBox
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: Mycroft.Units.gridUnit / 2
                        color: createThemeView.selectedTextColor
                        width: height
                    }

                    Label {
                        anchors.left: buttonTextColorPreviewBox.right
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 5
                        font.pixelSize: 24
                        font.bold: true
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        text: qsTr("Auto Text Color")
                    }
                }
                Rectangle {
                    id: setNameButton
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.5)
                    border.color: Kirigami.Theme.highlightColor
                    border.width: 1

                    Kirigami.Icon {
                        id: buttonIconNameBox
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: Mycroft.Units.gridUnit / 2
                        width: height
                        source: "edit-select-text"
                    }

                    Label {
                        anchors.left: buttonIconNameBox.right
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 5
                        font.pixelSize: 24
                        font.bold: true
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        text: qsTr("Set Name")
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                            setNameBoxPopup.open()
                        }
                    }
                }
            }

            Kirigami.Separator {
                id: themeSetterAreaBottomLine
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Kirigami.Theme.highlightColor
            }
        }

        Item {
            id: themePreviewArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: themeButtonArea.top
            height: Mycroft.Units.gridUnit * 5

            Rectangle {
                id: previewButtonArea
                anchors.fill: parent
                anchors.margins: Mycroft.Units.gridUnit / 2
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
                        id: previewButtonIcon
                        source: "actor"
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium

                        ColorOverlay {
                            anchors.fill: parent
                            source: previewButtonIcon
                            color: Kirigami.Theme.textColor
                        }
                    }

                    Kirigami.Heading {
                        level: 2
                        wrapMode: Text.WordWrap
                        font.bold: true
                        color: Kirigami.Theme.textColor
                        text: qsTr("Preview")
                        verticalAlignment: Text.AlignVCenter
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        previewPopUpBox.open()
                    }
                }
            }
        }
        Item {
            id: themeButtonArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Mycroft.Units.gridUnit * 5

            Rectangle {
                id: createButtonArea
                anchors.fill: parent
                anchors.margins: Mycroft.Units.gridUnit / 2
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
                        id: createButtonIcon
                        source: "checkmark"
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium

                        ColorOverlay {
                            anchors.fill: parent
                            source: createButtonIcon
                            color: Kirigami.Theme.textColor
                        }
                    }

                    Kirigami.Heading {
                        level: 2
                        wrapMode: Text.WordWrap
                        font.bold: true
                        color: Kirigami.Theme.textColor
                        text: qsTr("Create")
                        verticalAlignment: Text.AlignVCenter
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        Mycroft.MycroftController.sendRequest("ovos.shell.gui.color.scheme.generate", {"theme_name": createThemeView.selectedThemeName, "primaryColor": createThemeView.selectedPrimaryColor, "secondaryColor": createThemeView.selectedSecondaryColor, "textColor": createThemeView.selectedTextColor})
                        visualBusyIndicatorBox.visible = true
                        visualBusyIndicatorBox.enabled = true
                        timeoutMessageTimer.start()
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
            anchors.top: areaSep.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right

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
                color: Kirigami.Theme.textColor
                text: qsTr("Back")
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2
            }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: {
                Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                triggerGuiEvent("mycroft.device.settings.customize", {})
            }
        }
    }

    ItemDelegate  {
        id: previewPopUpBox
        width: parent.width * 0.9
        height: parent.height * 0.9
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        property bool opened: false
        visible: previewPopUpBox.opened
        enabled: previewPopUpBox.opened

        function open() {
            previewPopUpBox.opened = true
        }

        function close() {
            previewPopUpBox.opened = false
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
                    text: qsTr("Preview")
                    color: Kirigami.Theme.textColor
                    elide: Text.ElideRight
                }
            }

            RowLayout {
                anchors.top: popupHeaderArea.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: popupBottomArea.top
                anchors.margins: Mycroft.Units.gridUnit / 2

                ThemeView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    darkMode: true
                    viewPrimaryColor: createThemeView.selectedPrimaryColor
                    viewSecondaryColor: createThemeView.selectedSecondaryColor
                    viewTextColor: createThemeView.selectedTextColor
                    themeName: createThemeView.selectedThemeName
                    clickEnabled: false
                }

                ThemeView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    darkMode: false
                    viewPrimaryColor: createThemeView.selectedPrimaryColor
                    viewSecondaryColor: createThemeView.selectedSecondaryColor
                    viewTextColor: createThemeView.selectedTextColor
                    themeName: createThemeView.selectedThemeName
                    clickEnabled: false
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
                        text: qsTr("Cancel")
                        verticalAlignment: Text.AlignVCenter
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                        previewPopUpBox.close()
                    }
                }
            }
        }
    }

    Delegates.ColorSelectPrimary {
        id: primaryColorSelectorPopup
    }

    Delegates.ColorSelectSecondary {
        id: secondaryColorSelectorPopup
    }

    Delegates.SetNameBox {
        id: setNameBoxPopup
    }

    Rectangle {
        id: visualBusyIndicatorBox
        visible: false
        enabled: false
        color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.5)
        anchors.fill: parent

        Mycroft.BusyIndicator {
            anchors.centerIn: parent
            running: visualBusyIndicatorBox.visible ? 1 : 0
        }
    }
}

