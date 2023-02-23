import QtQuick.Layouts 1.4
import QtQuick 2.4
import QtQuick.Controls 2.0
import org.kde.kirigami 2.5 as Kirigami
import Mycroft 1.0 as Mycroft
import QtGraphicalEffects 1.12

Mycroft.Delegate {
    id: mainLoaderView
    property var pageToLoad: sessionData.state
    property var idleScreenList: sessionData.idleScreenList
    property var activeIdle: sessionData.selectedScreen
    property var imageUrl

    function getCurrentWallpaper() {
        Mycroft.MycroftController.sendRequest("ovos.wallpaper.manager.get.wallpaper", {})
    }

    Component.onCompleted: {
        getCurrentWallpaper()
    }

    Connections {
        target: Mycroft.MycroftController
        onIntentRecevied: {
            if (type == "ovos.wallpaper.manager.get.wallpaper.response") {
                imageUrl = data.url
            }
            if (type == "homescreen.wallpaper.set") {
                imageUrl = data.url
            }
        }
    }

    background: Item {
        Image {
            id: bgModelImage
            anchors.fill: parent
            source: Qt.resolvedUrl(mainLoaderView.imageUrl)
            fillMode: Image.PreserveAspectCrop
        }

        Rectangle {
            anchors.fill: parent
            color: Kirigami.Theme.backgroundColor
            opacity: 0.6
            z: 1
        }
    }

    contentItem: Loader {
        id: rootLoader
        z: 2
    }

    onPageToLoadChanged: {
        console.log(sessionData.state)
        rootLoader.setSource(sessionData.state + ".qml")
    }
}
