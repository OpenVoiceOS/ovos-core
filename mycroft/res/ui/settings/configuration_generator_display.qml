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
import QtQuick 2.9
import QtQuick.Controls 2.3
import org.kde.kirigami 2.11 as Kirigami
import QtGraphicalEffects 1.0
import Mycroft 1.0 as Mycroft

Item {
    id: configurationLoaderView
    anchors.fill: parent
    property var configurationData: sessionData.groupConfigurationData
    property var groupName: sessionData.groupName
    property var updateFieldList: []

    function selectSettingUpdated(modelData, key, value) {
        modelData.field_value = value
        var index = updateFieldList.findIndex(function(item) {
            return item.field_name == modelData.field_name
        })
        if (index == -1) {
            updateFieldList.push(modelData)
        } else {
            updateFieldList[index].field_value = value
        }
    }

    function generate_settings_ui(mData, comp) {
        console.log(mData.field_type, comp)

        if (mData.field_type == "bool") {
            var newObject = Qt.createComponent("configuration_ui/settingCheckBox.qml")
            var fieldDisplay = newObject.createObject(comp, {checked: mData.field_value.toString() == "true" ? 1 : 0, text: mData.field_value == "true" ? "Disable" : "Enable", "key": mData.field_name, "value": mData.field_value, "modelData": mData});
            fieldDisplay.fieldUpdated.connect(selectSettingUpdated)
        }
        if (mData.field_type == "str" || mData.field_type == "int" || mData.field_type == "float") {
            var newObject = Qt.createComponent("configuration_ui/settingTextBox.qml")
            var fieldDisplay = newObject.createObject(comp, {text: mData.field_value, "key": mData.field_name, "value": mData.field_value, "modelData": mData});
            fieldDisplay.fieldUpdated.connect(selectSettingUpdated)
        }
        if (mData.field_type == "list") {
            var listObject = []
            for (var lst=0; lst < mData.field_value.length; lst++){
                listObject.push(mData.field_value[lst])
            }
            console.log(listObject)
            var newObject = Qt.createComponent("configuration_ui/settingListBox.qml")
            var fieldDisplay = newObject.createObject(comp, {"value": mData.field_value, "key": mData.field_name, "modelData": mData});
            fieldDisplay.fieldUpdated.connect(selectSettingUpdated)
        }
    }

    function sanitize_values(mValues) {
        var val_listing = []
        for (var i = 0; i < mValues.length; i++) {
            if (mValues[i].includes('|')) {
                var splitVals = mValues[i].split("|")[1]
                val_listing.push(splitVals.toLowerCase())
            } else {
                val_listing.push(mValues[i])
            }
        }
        return val_listing
    }

    onConfigurationDataChanged: {
        configDataView.update()
        if(configurationData !== null){
            configDataView.model = configurationData.group_sections
            configPageHeading.text = groupName.toUpperCase() + " " + qsTr("Configuration")
        }
    }

    Item {
        id: topArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Kirigami.Units.gridUnit * 2

        Kirigami.Heading {
            id: configPageHeading
            level: 1
            wrapMode: Text.WordWrap
            anchors.centerIn: parent
            font.capitalization: Font.Capitalize
            font.bold: true
            color: Kirigami.Theme.linkColor
        }
    }

    Flickable {
        anchors.top: topArea.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomArea.top
        anchors.bottomMargin: Kirigami.Units.smallSpacing
        contentHeight: scvGrid.implicitHeight
        clip: true

        GridLayout {
            id: scvGrid
            width: parent.width
            columns: scvGrid.width > 850 ? 2 : 1
            rowSpacing: Kirigami.Units.smallSpacing

            Repeater {
                id: configDataView
                clip: true

                delegate: Control {
                    id: delegateRoot
                    Layout.alignment: Qt.AlignTop
                    Layout.fillWidth: true

                    background: Rectangle {
                        color: Qt.darker(Kirigami.Theme.backgroundColor, 2)
                        radius: 10
                    }

                    contentItem: Item {
                    implicitWidth: scvGrid.width > 850 ? scvGrid.width / 2 : scvGrid.width
                    implicitHeight: delegateLayout.implicitHeight + Kirigami.Units.largeSpacing

                        ColumnLayout {
                            id: delegateLayout
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: Kirigami.Units.largeSpacing

                            Rectangle {
                                id: skillNameBlock
                                color: Kirigami.Theme.linkColor
                                Layout.fillWidth: true
                                Layout.margins: Kirigami.Units.largeSpacing
                                Layout.preferredHeight: skillName.contentHeight + Kirigami.Units.smallSpacing
                                radius: 3

                                Kirigami.Heading {
                                    id: skillName
                                    elide: Text.ElideRight
                                    font.weight: Font.DemiBold
                                    text: modelData.section_label
                                    width: parent.width
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                    level: 2
                                }
                            }

                            Repeater {
                                id: sectionFieldsDisplay
                                model: modelData.section_fields

                                delegate: GridLayout {
                                    id: configGridBox
                                    Layout.fillWidth: true
                                    Layout.margins: Kirigami.Units.largeSpacing / 2
                                    Layout.alignment: Qt.AlignLeft | Qt.AlignTop

                                    columns: switch(modelData.field_type) {
                                        case "str":
                                            if(modelData.field_description.length > 2){
                                                return 1;
                                            } else {
                                                return 2;
                                            }
                                        case "bool":
                                            if(modelData.field_description.length > 2){
                                                return 1;
                                            } else {
                                                return 2;
                                            }
                                        case "list": return 1;
                                        default: return 2;
                                    }

                                    Kirigami.Heading {
                                        id: configTopFieldLabel
                                        Layout.alignment: Qt.AlignLeft
                                        elide: Text.ElideRight
                                        text: modelData.field_label
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap;
                                        font.capitalization: Font.Capitalize
                                        textFormat: Text.AutoText
                                        level: 3
                                    }

                                    Label {
                                        id: configTopFieldDescription
                                        Layout.alignment: Qt.AlignLeft
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap;
                                        elide: Text.ElideRight
                                        text: modelData.field_description
                                        visible: modelData.field_description.length > 2 ? 1 : 0
                                        enabled: modelData.field_description.length > 2 ? 1 : 0
                                        font.pixelSize: configTopFieldLabel.font.pixelSize * 0.75
                                    }

                                    ButtonGroup {
                                        id: settingGroup
                                    }

                                    Component.onCompleted: {
                                        generate_settings_ui(modelData, configGridBox)
                                        configDataView.update()
                                    }
                                }
                            }
                        }
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
                    Mycroft.MycroftController.sendRequest("ovos.phal.configuration.provider.list.groups", {})
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
                    text: qsTr("Update Settings")
                    horizontalAlignment: Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                }

                Kirigami.Icon {
                    id: nextIcon
                    source: "run-build-configure"
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
                    Mycroft.MycroftController.sendRequest("ovos.phal.configuration.provider.set", {"configuration": configurationLoaderView.updateFieldList, "group_name": configurationLoaderView.groupName})
                    Mycroft.MycroftController.sendRequest("ovos.phal.configuration.provider.list.groups", {})
                }
            }
        }
    }
}
