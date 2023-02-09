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

Item {
    id: customizeSettingsView
    anchors.fill: parent
    property var colorSchemeModel
    property var setColorScheme

    Component.onCompleted: {
        OVOSPlugin.Configuration.updateSchemeList();
        colorSchemeModel = OVOSPlugin.Configuration.getSchemeList();
        colorSchemesView.model = colorSchemeModel.schemes;
        setColorScheme = OVOSPlugin.Configuration.getSelectedSchemeName();
        console.log(setColorScheme);
    }

    Connections {
        target: OVOSPlugin.Configuration
        onSchemeChanged: {
            setColorScheme = OVOSPlugin.Configuration.getSelectedSchemeName();
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
            text: qsTr("Customize Settings")
            color: Kirigami.Theme.textColor
        }
    }

    Item {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top

        GridView {
            id: colorSchemesView
            width: parent.width
            height: parent.height
            cellWidth: parent.width / 3
            cellHeight: parent.height / 2
            clip: true

            delegate: ItemDelegate {
                id: parentRectDelta
                implicitHeight: colorSchemesView.cellHeight - (Mycroft.Units.largeSpacing * 2)
                implicitWidth: colorSchemesView.cellWidth - (Mycroft.Units.largeSpacing * 2)

                background: Rectangle {
                    color: modelData.primaryColor
                    radius: 10
                }

                Item {
                    id: d1item
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
                            color: modelData.primaryColor
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
                                color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                                font.bold: true
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: modelData.secondaryColor
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
                                color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                                font.bold: true
                            }
                        }
                        Rectangle{
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: modelData.textColor
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
                                color: Qt.darker(Kirigami.Theme.textColor, 1.5)
                                font.bold: true
                            }
                        }
                        Rectangle{
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            visible: modelData.name == setColorScheme ? 1 : 0
                            enabled: modelData.name == setColorScheme ? 1 : 0
                            color: "transparent"

                            Kirigami.Icon {
                                anchors.fill: parent
                                anchors.margins: 4
                                source: Qt.resolvedUrl("images/tick.svg")
                                color: Kirigami.Theme.textColor
                            }
                        }
                    }
                }

                Kirigami.Separator {
                    id: cardSept
                    anchors.top: d1item.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 16
                    color: modelData.secondaryColor
                }

                Item {
                    id: d2item
                    anchors.top: cardSept.bottom
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
                        text: modelData.name
                        color: modelData.textColor
                        elide: Text.ElideRight
                    }
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    styleViewPopUp.showView(modelData.name, modelData.path, modelData.primaryColor, modelData.secondaryColor, modelData.textColor)
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

        Item {
            anchors.top: areaSep.bottom
            anchors.bottom: parent.bottom
            width: parent.width / 2
            anchors.left: parent.left

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
                    color: Kirigami.Theme.textColor
                    text: qsTr("Device Settings")
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

        Item {
            anchors.top: areaSep.bottom
            anchors.bottom: parent.bottom
            width: parent.width / 2
            anchors.right: parent.right

            RowLayout {
                anchors.fill: parent

                Kirigami.Heading {
                    level: 2
                    wrapMode: Text.WordWrap
                    font.bold: true
                    color: Kirigami.Theme.textColor
                    text: qsTr("Create Scheme")
                    horizontalAlignment: Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                }

                Kirigami.Icon {
                    id: nextIcon
                    source: Qt.resolvedUrl("images/next.svg")
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.alignment: Qt.AlignRight

                    ColorOverlay {
                        anchors.fill: parent
                        source: nextIcon
                        color: Kirigami.Theme.textColor
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    triggerGuiEvent("mycroft.device.settings.create.theme", {})
                }
            }
        }
    }

    ItemDelegate  {
        id: styleViewPopUp
        width: parent.width * 0.9
        height: parent.height * 0.9
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        property var modelDataPath
        property var modelDataName
        property color primaryColor
        property color secondaryColor
        property color textColor
        property bool opened: false
        visible: opened
        enabled: opened

        function open(){
            styleViewPopUp.opened = true
        }

        function close(){
            styleViewPopUp.opened = false
        }

        function showView(modelDataName, modelDataPath, primaryColor, secondaryColor, textColor) {
            styleViewPopUp.primaryColor = primaryColor
            styleViewPopUp.secondaryColor = secondaryColor
            styleViewPopUp.textColor = textColor
            styleViewPopUp.modelDataName = modelDataName
            styleViewPopUp.modelDataPath = modelDataPath
            styleViewPopUp.open()
        }

        function setTheme(themeStyle) {
            OVOSPlugin.Configuration.setScheme(styleViewPopUp.modelDataName, styleViewPopUp.modelDataPath, themeStyle)
            styleViewPopUp.close()
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
                    text: qsTr("Select Style")
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
                    viewPrimaryColor: styleViewPopUp.primaryColor
                    viewSecondaryColor: styleViewPopUp.secondaryColor
                    viewTextColor: styleViewPopUp.textColor
                    themeName: styleViewPopUp.modelDataName
                }

                ThemeView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    darkMode: false
                    viewPrimaryColor: styleViewPopUp.primaryColor
                    viewSecondaryColor: styleViewPopUp.secondaryColor
                    viewTextColor: styleViewPopUp.textColor
                    themeName: styleViewPopUp.modelDataName
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
                        styleViewPopUp.close()
                    }
                }
            }
        }
    }
}

