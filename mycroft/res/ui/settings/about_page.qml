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
    id: customizeSettingsView
    anchors.fill: parent
    property var systemInformation: sessionData.system_info

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
            text: qsTr("About")
            color: Kirigami.Theme.textColor
        }
    }

    Item {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top

        Rectangle {
            id: sysInfoHeaderBox
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: Mycroft.Units.gridUnit * 4
            color: Kirigami.Theme.highlightColor

            Kirigami.Heading {
                font.pixelSize: 25
                fontSizeMode: Text.Fit
                minimumPixelSize: 5
                anchors.fill: parent
                anchors.margins: Mycroft.Units.gridUnit / 2
                horizontalAlignment: Text.AlignLeft
                verticalAlignment: Text.AlignVCenter
                level: 2
                wrapMode: Text.WrodWrap
                font.bold: true
                font.weight: Font.ExtraBold
                text: qsTr("System Information")
                color: Kirigami.Theme.textColor
            }
        }

        ColumnLayout {
            anchors.top: sysInfoHeaderBox.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Mycroft.Units.gridUnit / 2

            Label {
                text: "<b>" + qsTr("Kernel Version") + ":</b> " + systemInformation.uname_kernelversion
                font.pixelSize: 25
                fontSizeMode: Text.Fit
                minimumPixelSize: 5
                color: Kirigami.Theme.textColor
                Layout.alignment: Qt.AlignLeft
            }
            Label {
                text: "<b>OpenVoiceOS Core " + qsTr("Version") + ":</b> " + systemInformation.ovos_core_version
                font.pixelSize: 25
                fontSizeMode: Text.Fit
                minimumPixelSize: 5
                color: Kirigami.Theme.textColor
                Layout.alignment: Qt.AlignLeft
            }
            Label {
                text: "<b>Python " + qsTr("Version")+ ":</b> " + systemInformation.python_version
                font.pixelSize: 25
                fontSizeMode: Text.Fit
                minimumPixelSize: 5
                color: Kirigami.Theme.textColor
                Layout.alignment: Qt.AlignLeft
            }
            Label {
                text: "<b>" + qsTr("Local Address") + ":</b> " + systemInformation.local_address
                font.pixelSize: 25
                fontSizeMode: Text.Fit
                minimumPixelSize: 5
                color: Kirigami.Theme.textColor
                Layout.alignment: Qt.AlignLeft

                Component.onCompleted: {
                    if(!systemInformation.local_address) {
                        text = "<b>" + qsTr("Local Address") + ":</b> " + qsTr("No Active Connection")
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
            }
        }
    }
}

