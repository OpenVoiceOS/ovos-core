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
import QtQuick 2.4
import QtQuick.Controls 2.0
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.kirigami 2.5 as Kirigami
import Mycroft 1.0 as Mycroft
import QtGraphicalEffects 1.12

Item {
    id: advancedConfigurationGroupsView
    anchors.fill: parent

    Item {
        id: topArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Kirigami.Units.gridUnit * 2

        Kirigami.Heading {
            id: advancedConfigurationGroupsViewHeading
            level: 1
            wrapMode: Text.WordWrap
            anchors.centerIn: parent
            font.bold: true
            text: qsTr("Advanced Configuration")
            color: Kirigami.Theme.textColor
        }
    }

    ColumnLayout {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top
        anchors.bottomMargin: Kirigami.Units.largeSpacing

        Kirigami.Heading {
            id: warnText
            level: 3
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.textColor
            text: "<b> All configuration changes made here can alter the functionality of your device, some changes might also require a reboot to take affect </b>"
        }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.largeSpacing
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: sessionData.groupList
            boundsBehavior: Flickable.StopAtBounds

            delegate: Kirigami.AbstractListItem {
                activeBackgroundColor: Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.7)
                contentItem: Item {
                implicitWidth: delegateLayout.implicitWidth;
                implicitHeight: delegateLayout.implicitHeight;

                    RowLayout {
                        id: delegateLayout
                        spacing: Mycroft.Units.gridUnit / 2

                        anchors {
                            left: parent.left;
                            top: parent.top;
                            right: parent.right;
                        }

                        Kirigami.Icon {
                            id: iconGroupHolder
                            source: "beamerblock"
                            Layout.preferredWidth: Mycroft.Units.gridUnit * 2
                            Layout.preferredHeight: Mycroft.Units.gridUnit * 2

                            ColorOverlay {
                                anchors.fill: parent
                                source: iconGroupHolder
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
                            font.capitalization: Font.Capitalize
                            text: modelData.replace("_", " ")
                            textFormat: Text.PlainText
                            color: Kirigami.Theme.textColor
                            level: 2
                        }
                    }
                }

                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../snd/clicked.wav"))
                    Mycroft.MycroftController.sendRequest("ovos.phal.configuration.provider.get", {"group": modelData})
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
                text: qsTr("Back")
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
                triggerGuiEvent("mycroft.device.settings.developer", {})
            }
        }
    }
}
