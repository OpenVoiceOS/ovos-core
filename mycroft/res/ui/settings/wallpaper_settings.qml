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
    id: wallpaperSettings
    anchors.fill: parent
    property var currentProvider
    property var currentWallpaper
    property var providersModel
    property var wallpapersProviderCollection
    property bool providerHasCollection
    property bool providerIsConfigurable
    property bool wallpaperRotation: false

    Connections {
        target: Mycroft.MycroftController
        onIntentRecevied: {
            if (type == "ovos.wallpaper.manager.get.active.provider.response") {
                currentProvider = data.active_provider
            }
            if (type == "ovos.wallpaper.manager.get.registered.providers.response") {
                var model = {"providers": data.registered_providers}
                providersModel = model.providers
                providersComboBox.model = providersModel
            }
            if (type == "ovos.wallpaper.manager.get.wallpaper.response") {
                currentWallpaper = data.url
            }
            if (type == "ovos.wallpaper.manager.get.auto.rotation.response") {
                wallpaperRotation = data.auto_rotation
            }
            if (type == "ovos.wallpaper.manager.get.provider.config.response") {
                configureProviderPopupDialog.providerName = data.provider_name
                configureProviderPopupDialog.providerConfiguration = convertConfigToArray(data.config)
            }
            if (type == "homescreen.wallpaper.set") {
                currentWallpaper = data.url
            }
            if (type == "ovos.phal.wallpaper.manager.provider.registered") {
                getRegisteredProviders()
            }
        }
    }

    function getActiveProvider() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.active.provider", {})
    }

    function getRegisteredProviders() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.registered.providers", {})
    }

    function getCurrentWallpaper() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.wallpaper", {})
    }

    function getAutoRotation() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.auto.rotation", {})
    }

    function refreshProvider() {
        var idx = providersComboBox.currentIndex
        wallpapersProviderCollection = providersComboBox.model[idx].wallpaper_collection
        providerIsConfigurable = providersComboBox.model[idx].provider_configurable
        if(wallpapersProviderCollection.length > 0) {
            providerHasCollection = true
        } else {
            providerHasCollection = false
        }
        wallpapersView.forceLayout()
    }

    function getProviderConfig() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.provider.config", {"provider_name": providersComboBox.currentValue})
    }

    function convertConfigToArray(obj) {
        var result = [];
        for (var key in obj) {
            result.push({ "key": key, "value": obj[key].toLowerCase() });
        }
        return result;
    }

    function convertArrayToObject(keyValueArray) {
        var result = {};
        for (var i = 0; i < keyValueArray.length; i++) {
            var obj = keyValueArray[i];
            result[obj.key] = obj.value;
        }
        return result;
    }

    Component.onCompleted: {
        getActiveProvider()
        getRegisteredProviders()
        getCurrentWallpaper()
        getAutoRotation()
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
            text: qsTr("Wallpaper Settings")
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

    RowLayout {
        id: wallpaperProviderSelector
        anchors.top: topArea.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: Mycroft.Units.gridUnit * 4

        ComboBox {
            id: providersComboBox
            Layout.fillWidth: true
            Layout.fillHeight: true
            textRole: "provider_display_name"
            valueRole: "provider_name"

            onModelChanged: {
                refreshProvider()
            }

            onCurrentValueChanged: {
                refreshProvider()
            }
        }

        Button {
            id: setProviderButton
            Layout.preferredWidth: Mycroft.Units.gridUnit * 12
            Layout.fillHeight: true
            enabled: providersComboBox.currentValue != currentProvider ? 1 : 0

            background: Rectangle {
                radius: 4
                color: setProviderButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
            }

            contentItem: Item {
                RowLayout {
                    anchors.centerIn: parent
                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        source: "dialog-ok"
                    }
                    Label {
                        color: setProviderButton.enabled ? Kirigami.Theme.textColor : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                        text: qsTr("Set Provider")
                    }
                }
            }

            onClicked: {
                Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.set.active.provider", {"provider_name": providersComboBox.currentValue})
                getActiveProvider()
                getCurrentWallpaper()
                refreshProvider()
            }
        }

        Button {
            id: configureProviderButton
            Layout.preferredWidth: Mycroft.Units.gridUnit * 12
            Layout.fillHeight: true
            enabled: wallpaperSettings.providerIsConfigurable

            background: Rectangle {
                radius: 4
                color: configureProviderButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
            }

            contentItem: Item {
                RowLayout {
                    anchors.centerIn: parent
                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        source: "configure"
                    }
                    Label {
                        color: configureProviderButton.enabled ? Kirigami.Theme.textColor : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                        text: qsTr("Configure")
                    }
                }
            }

            onClicked: {
                getProviderConfig()
                configureProviderPopupDialog.open()
            }
        }
    }

    Rectangle {
        anchors.top: wallpaperProviderSelector.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.left: parent.left
        anchors.right: flickAreaScrollBar.left
        anchors.leftMargin: Mycroft.Units.gridUnit
        anchors.bottom: bottomArea.top
        anchors.bottomMargin: Kirigami.Units.largeSpacing
        color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.7)
        border.color: Kirigami.Theme.backgroundColor
        border.width: 1
        radius: 4

        Rectangle {
            id: collectionNotAvailableView
            anchors.centerIn: parent
            width: parent.width - (Mycroft.Units.gridUnit / 2)
            height: Mycroft.Units.gridUnit * 4
            color: Kirigami.Theme.backgroundColor
            border.color: Kirigami.Theme.highlightColor
            border.width: 1
            visible: !wallpaperSettings.providerHasCollection ? 1 : 0
            enabled: !wallpaperSettings.providerHasCollection ? 1 : 0
            radius: 4

            Label {
                id: collectionNotAvailableViewLabel
                anchors.fill: parent
                anchors.margins: Mycroft.Units.gridUnit / 2
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.textColor
                text: qsTr("This provider generates new wallpapers dynamically instead of wallpaper collections.")
            }
        }

        GridView {
            id: wallpapersView
            anchors.centerIn: parent
            width: parent.width - (Mycroft.Units.gridUnit / 2)
            height: parent.height - (Mycroft.Units.gridUnit / 2)
            ScrollBar.vertical: flickAreaScrollBar
            visible: wallpaperSettings.providerHasCollection ? 1 : 0
            enabled: wallpaperSettings.providerHasCollection ? 1 : 0
            cellWidth: width / 4
            cellHeight: cellWidth - Mycroft.Units.gridUnit * 2
            clip: true
            model: wallpaperSettings.wallpapersProviderCollection
            delegate: ItemDelegate {
                width: wallpapersView.cellWidth
                height: wallpapersView.cellHeight
                padding: 4

                background: Rectangle {
                    color: "transparent"
                }

                contentItem: Rectangle {
                    color: Kirigami.Theme.backgroundColor
                    border.color: currentWallpaper == modelData ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
                    border.width: 2

                    Image {
                        id: delegateImage
                        anchors.fill: parent
                        anchors.margins: 4
                        source: Qt.resolvedUrl(modelData)
                    }
                }

                onClicked: {
                    if(modelData != currentWallpaper) {
                        setWallpaperPopupDialog.open(modelData)
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

    ItemDelegate {
        id: setWallpaperPopupDialog
        width: wallpaperSettings.width
        height: wallpaperSettings.height
        property bool opened: false
        visible: setWallpaperPopupDialog.opened ? 1 : 0
        enabled: setWallpaperPopupDialog.opened ? 1 : 0
        property var imageUrl

        function open(url) {
            setWallpaperPopupDialog.imageUrl = url
            setWallpaperPopupDialog.opened = true
        }

        function close() {
            setWallpaperPopupDialog.opened = false
        }

        background: Item {

            Image {
                id: bgModelImage
                anchors.fill: parent
                anchors.margins: Mycroft.Units.gridUnit * 2
                source: Qt.resolvedUrl(setWallpaperPopupDialog.imageUrl)
                smooth: true
            }

            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.6)
            }
        }

        contentItem: Item {
            width: wallpaperSettings.width
            height: wallpaperSettings.height

            Item {
                anchors.centerIn: parent
                width: parent.width / 1.5
                height: parent.height / 1.5

                Column {
                    anchors.fill: parent
                    spacing: Mycroft.Units.gridUnit / 2

                    RowLayout {
                        id: warningMessageWallpaperRotation
                        width: parent.width
                        height: Mycroft.Units.gridUnit * 4
                        enabled: wallpaperSettings.wallpaperRotation
                        visible: wallpaperSettings.wallpaperRotation

                        Kirigami.Icon {
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            Layout.alignment: Layout.AlignVCenter
                            source: "state-warning"
                        }

                        Label {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: Kirigami.Theme.textColor
                            font.bold: true
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignVCenter
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            text: qsTr("Wallpaper rotation prevents setting new wallpapers, disable wallpaper rotation and try again")
                        }
                    }

                    Button {
                        id: setWallpaperButton
                        width: parent.width
                        height: Mycroft.Units.gridUnit * 3
                        enabled: wallpaperSettings.wallpaperRotation ? 0 : 1

                        background: Rectangle {
                            radius: 4
                            color: setWallpaperButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
                        }

                        contentItem: Item {
                            RowLayout {
                                anchors.centerIn: parent
                                Kirigami.Icon {
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                    source: "dialog-ok"
                                }
                                Label {
                                    color: setWallpaperButton.enabled ? Kirigami.Theme.textColor : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                                    text: qsTr("Set Wallpaper")
                                }
                            }
                        }

                        onClicked: {
                            if(currentProvider == providersComboBox.currentValue) {
                                Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.set.wallpaper", {"url": setWallpaperPopupDialog.imageUrl})
                                setWallpaperPopupDialog.close()
                                getCurrentWallpaper()
                            } else {
                                Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.set.active.provider", {"provider_name": providersComboBox.currentValue, "provider_image": setWallpaperPopupDialog.imageUrl})
                                getActiveProvider()
                                getCurrentWallpaper()
                                refreshProvider()
                            }
                        }

                        Keys.onReturnPressed: {
                            clicked()
                        }

                    }

                    Button {
                        id: rejectButton
                        width: parent.width
                        height: Mycroft.Units.gridUnit * 3

                        background: Rectangle {
                            radius: 4
                            color: rejectButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
                        }

                        contentItem: Item {
                            RowLayout {
                                anchors.centerIn: parent
                                Kirigami.Icon {
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                    source: "dialog-cancel"
                                }
                                Label {
                                    color: Kirigami.Theme.textColor
                                    text: qsTr("Cancel")
                                }
                            }
                        }

                        onClicked: {
                            setWallpaperPopupDialog.close()
                        }

                        Keys.onReturnPressed: {
                            clicked()
                        }
                    }
                }
            }
        }
    }

    ItemDelegate {
        id: configureProviderPopupDialog
        width: wallpaperSettings.width
        height: wallpaperSettings.height
        property bool opened: false
        visible: configureProviderPopupDialog.opened ? 1 : 0
        enabled: configureProviderPopupDialog.opened ? 1 : 0
        property var providerName
        property var providerConfiguration
        property var newConfiguration: []

        function open() {
            configureProviderPopupDialog.opened = true
        }

        function close() {
            providerConfiguration = {}
            configureProviderPopupDialog.opened = false
        }

        background: Rectangle {
            color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b, 0.6)
        }

        contentItem: Item {
            width: wallpaperSettings.width
            height: wallpaperSettings.height

            Item {
                anchors.centerIn: parent
                width: parent.width / 1.5
                height: parent.height / 1.5

                Column {
                    anchors.fill: parent
                    spacing: Mycroft.Units.gridUnit / 2

                    Repeater {
                        model: configureProviderPopupDialog.providerConfiguration
                        delegate: RowLayout {
                            width: parent.width
                            height: Mycroft.Units.gridUnit * 3

                            Label {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                color: Kirigami.Theme.textColor
                                font.capitalization: Font.AllUppercase
                                text: modelData.key
                            }

                            TextField {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                text: modelData.value

                                onTextChanged: {
                                    var keyExists = false
                                    for (var i = 0; i < configureProviderPopupDialog.newConfiguration.length; i++) {
                                        if (configureProviderPopupDialog.newConfiguration[i].key === modelData.key) {
                                            configureProviderPopupDialog.newConfiguration[i].value = text
                                            keyExists = true
                                        }
                                    }
                                    if (!keyExists) {
                                        configureProviderPopupDialog.newConfiguration.push({
                                            "key": modelData.key,
                                            "value": text
                                        })
                                    }
                                }
                            }
                        }
                    }

                    Button {
                        id: setProviderConfigurationButton
                        width: parent.width
                        height: Mycroft.Units.gridUnit * 3

                        background: Rectangle {
                            radius: 4
                            color: setProviderConfigurationButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
                        }

                        contentItem: Item {
                            RowLayout {
                                anchors.centerIn: parent
                                Kirigami.Icon {
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                    source: "dialog-ok"
                                }
                                Label {
                                    color: setWallpaperButton.enabled ? Kirigami.Theme.textColor : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.5)
                                    text: qsTr("Apply Configuration")
                                }
                            }
                        }

                        onClicked: {
                            var config = convertArrayToObject(configureProviderPopupDialog.newConfiguration)
                            Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.set.provider.config", 
                            {"provider_name": configureProviderPopupDialog.providerName, "config": config}) 
                            configureProviderPopupDialog.close()
                        }

                        Keys.onReturnPressed: {
                            clicked()
                        }
                    }

                    Button {
                        id: rejectConfigurationButton
                        width: parent.width
                        height: Mycroft.Units.gridUnit * 3

                        background: Rectangle {
                            radius: 4
                            color: rejectConfigurationButton.activeFocus ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
                        }

                        contentItem: Item {
                            RowLayout {
                                anchors.centerIn: parent
                                Kirigami.Icon {
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                    source: "dialog-cancel"
                                }
                                Label {
                                    color: Kirigami.Theme.textColor
                                    text: qsTr("Cancel")
                                }
                            }
                        }

                        onClicked: {
                            configureProviderPopupDialog.close()
                        }

                        Keys.onReturnPressed: {
                            clicked()
                        }
                    }
                }
            }
        }
    }
}
