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
import Mycroft 1.0 as Mycroft

ColumnLayout {
    id: listGeneratedItem
    property var modelData
    property var key
    property var value
    Layout.fillWidth: true
    property bool editMode: false
    signal fieldUpdated(var modelData, string key, string value);

    onValueChanged: {
        fieldUpdated(modelData, key, value)
    }

    function add_item_to_value(item) {
        listGeneratedItem.value.push(item)
        simpleListView.visible = false
        simpleListView.model = [0, 0, 0]
        simpleListView.enabled = false
        simpleListView.enabled = true
        simpleListView.visible = true
        simpleListView.model = listGeneratedItem.value
    }

    function remove_item_from_value(itemIndex) {
        listGeneratedItem.value.pop(itemIndex)
        simpleListView.visible = false
        simpleListView.model = [0, 0, 0]
        simpleListView.enabled = false
        simpleListView.enabled = true
        simpleListView.visible = true
        simpleListView.model = listGeneratedItem.value
    }

    Repeater {
        id: simpleListView
        model: listGeneratedItem.value

        delegate: Kirigami.AbstractListItem {
            width: simpleListView.width
            height: Mycroft.Units.gridUnit * 4

            background: Rectangle {
                color: Kirigami.Theme.backgroundColor
                radius: 6
            }

            contentItem: RowLayout {
                Label {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: modelData
                }

                Button {
                    Layout.preferredWidth: Mycroft.Units.gridUnit * 6
                    Layout.fillHeight: true
                    visible: listGeneratedItem.editMode ? 1 : 0
                    enabled: listGeneratedItem.editMode ? 1 : 0

                    background: Rectangle {
                        color: Kirigami.Theme.highlightColor
                        radius: 6
                    }

                    contentItem: Item {
                        Kirigami.Icon {
                            anchors.fill: parent
                            anchors.margins: Mycroft.Units.gridUnit / 2
                            source: "edit-delete-remove"
                            color: Kirigami.Theme.textColor
                        }
                    }

                    onClicked: {
                        listGeneratedItem.remove_item_from_value(index)
                    }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: Mycroft.Units.gridUnit * 4

        Button {
            Layout.fillWidth: true
            Layout.preferredHeight: Mycroft.Units.gridUnit * 3.5
            Layout.alignment: Qt.AlignVCenter

            background: Rectangle {
                color: Kirigami.Theme.highlightColor
                radius: 6
            }

            contentItem: Item {
                Kirigami.Icon {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit / 2
                    source: "list-add-symbolic"
                    color: Kirigami.Theme.textColor
                }
            }

            onClicked: {
                addListItemBox.privateItem = listGeneratedItem
                addListItemBox.open()
            }
        }

        Button {
            Layout.fillWidth: true
            Layout.preferredHeight: Mycroft.Units.gridUnit * 3.5
            Layout.alignment: Qt.AlignVCenter
            enabled: simpleListView.count > 0 ? 1 : 0
            visible: simpleListView.count > 0 ? 1 : 0

            background: Rectangle {
                color: Kirigami.Theme.highlightColor
                radius: 6
            }

            contentItem: Item {
                Kirigami.Icon {
                    anchors.fill: parent
                    anchors.margins: Mycroft.Units.gridUnit / 2
                    source: "document-edit"
                    color: Kirigami.Theme.textColor
                }
            }

            onClicked: {
                if(!listGeneratedItem.editMode) {
                    listGeneratedItem.editMode = true
                } else {
                    listGeneratedItem.editMode = false
                }
            }
        }
    }

    Popup {
        id: addListItemBox
        width: parent.width * 0.80
        height: Mycroft.Units.gridUnit * 8
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        parent: configurationLoaderView
        property var privateItem

        ColumnLayout {
            anchors.fill: parent

            TextField {
                id: addListItemTextBox
                Layout.fillWidth: true
                Layout.preferredHeight: Mycroft.Units.gridUnit * 4
                placeholderText: qsTr("Type here to add an item to the list")
            }

            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: Mycroft.Units.gridUnit * 2

                background: Rectangle {
                    color: Kirigami.Theme.highlightColor
                    radius: 6
                }

                contentItem: Label {
                    text: qsTr("Add Item")
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                onClicked: {
                    addListItemBox.privateItem.add_item_to_value(addListItemTextBox.text)
                    addListItemBox.close()
                }
            }
        }
    }
}
