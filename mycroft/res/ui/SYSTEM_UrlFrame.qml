import QtQuick.Layouts 1.4
import QtQuick 2.12
import QtQuick.Controls 2.12
import org.kde.kirigami 2.11 as Kirigami
import QtWebEngine 1.8
import Mycroft 1.0 as Mycroft

Mycroft.AbstractDelegate {
    id: systemUrlFrame
    property var pageUrl: sessionData.url

    onPageUrlChanged: {
        if(typeof pageUrl !== "undefined" || typeof pageUrl !== null){
            webview.url = pageUrl
        }
    }

    contentItem: Item {
        anchors.fill: parent

        Rectangle {
            id: blankArea
            color: Kirigami.Theme.backgroundColor
            height: Mycroft.Units.gridUnit * 2
            anchors.top: parent.top
            width: parent.width
        }

        SwipeArea {
            anchors.top: blankArea.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            preventStealing: true

            Flickable {
                id: flickable
                clip: true;
                anchors.fill: parent
                contentHeight: systemUrlFrame.height * 2
                contentWidth: systemUrlFrame.width

                property var storeCHeight
                property var storeCWidth

                WebEngineView {
                    id: webview
                    anchors.fill : parent;
                    profile: defaultProfile

                    settings.autoLoadImages: true
                    settings.javascriptEnabled: true
                    settings.errorPageEnabled: true
                    settings.pluginsEnabled: true
                    settings.allowWindowActivationFromJavaScript: true
                    settings.javascriptCanOpenWindows: true
                    settings.fullScreenSupportEnabled: true
                    settings.autoLoadIconsForPage: true
                    settings.touchIconsEnabled: true
                    settings.webRTCPublicInterfacesOnly: true
                    settings.showScrollBars: false

                    onNewViewRequested: function(request) {
                        if (!request.userInitiated) {
                            console.log("Warning: Blocked a popup window.");
                        } else if (request.destination === WebEngineView.NewViewInDialog) {
                            popuproot.open()
                            request.openIn(popupwebview);
                        } else {
                            request.openIn(webview);
                        }
                    }

                    onJavaScriptDialogRequested: function(request) {
                        request.accepted = true;
                    }

                    onFeaturePermissionRequested: {
                        interactionBar.setSource("FeatureRequest.qml")
                        interactionBar.interactionItem.securityOrigin = securityOrigin;
                        interactionBar.interactionItem.requestedFeature = feature;
                        interactionBar.isRequested = true;
                    }

                    onFullScreenRequested: function(request) {
                        if (request.toggleOn) {
                            flickable.storeCWidth = flickable.contentWidth
                            flickable.storeCHeight = flickable.contentHeight
                            flickable.contentWidth = flickable.width
                            flickable.contentHeight = flickable.height
                        }
                        else {
                            flickable.contentWidth = flickable.storeCWidth
                            flickable.contentHeight = flickable.storeCHeight
                        }
                        request.accept()
                    }

                    onLoadingChanged: {
                        if (loadRequest.status !== WebEngineView.LoadSucceededStatus) {
                            return;
                        }

                        flickable.contentHeight = 0;
                        flickable.contentWidth = flickable.width;

                        runJavaScript (
                            "document.documentElement.scrollHeight;",
                            function (actualPageHeight) {
                                flickable.contentHeight = Math.max (
                                    actualPageHeight, flickable.height);
                        });
                    }
                }

                WebEngineProfile {
                    id: defaultProfile
                    httpUserAgent: "Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Mobile Safari/537.36"
                }

                onFlickEnded: {
                    webview.runJavaScript (
                        "document.documentElement.scrollHeight;",
                        function (actualPageHeight) {
                            flickable.contentHeight = Math.max (
                                actualPageHeight, flickable.height);
                    });
                }
            }

            RequestHandler {
                id: interactionBar
                anchors.top: parent.top
                z: 1001
            }

            Popup {
                id: popuproot
                modal: true
                focus: true
                width: root.width - Kirigami.Units.largeSpacing * 1.25
                height: root.height - Kirigami.Units.largeSpacing * 1.25
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                anchors.centerIn: parent

                WebEngineView {
                    id: popupwebview
                    anchors.fill: parent
                    url: "about:blank"
                    settings.autoLoadImages: true
                    settings.javascriptEnabled: true
                    settings.errorPageEnabled: true
                    settings.pluginsEnabled: true
                    settings.allowWindowActivationFromJavaScript: true
                    settings.javascriptCanOpenWindows: true
                    settings.fullScreenSupportEnabled: true
                    settings.autoLoadIconsForPage: true
                    settings.touchIconsEnabled: true
                    settings.webRTCPublicInterfacesOnly: true
                    property string urlalias: popupwebview.url

                    onNewViewRequested: function(request) {
                        console.log(request.destination)
                    }
                }
            }
        }
    }
}
