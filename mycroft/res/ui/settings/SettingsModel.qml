import QtQuick.Layouts 1.4
import QtQuick 2.4
import QtQuick.Controls 2.0
import org.kde.kirigami 2.5 as Kirigami
import Mycroft 1.0 as Mycroft

ListModel {
    id: settingsListModel

    ListElement {
        settingIcon: "images/home.svg"
        settingName: QT_TR_NOOP("Homescreen Settings")
        settingEvent: "mycroft.device.settings.homescreen"
        settingCall: "show homescreen settings"
    }
    ListElement {
        settingIcon: "images/paint.svg"
        settingName: QT_TR_NOOP("Customize")
        settingEvent: "mycroft.device.settings.customize"
        settingCall: ""
    }
    ListElement {
        settingIcon: "images/display.svg"
        settingName: QT_TR_NOOP("Display")
        settingEvent: "mycroft.device.settings.display"
        settingCall: ""
    }
    ListElement {
        settingIcon: "images/ssh.svg"
        settingName: QT_TR_NOOP("Enable SSH")
        settingEvent: "mycroft.device.settings.ssh"
        settingCall: "show ssh settings"
    }
    ListElement {
        settingIcon: "images/settings.png"
        settingName: QT_TR_NOOP("Developer Settings")
        settingEvent: "mycroft.device.settings.developer"
        settingCall: ""
    }
    ListElement {
        settingIcon: "images/info.svg"
        settingName: QT_TR_NOOP("About")
        settingEvent: "mycroft.device.settings.about.page"
        settingCall: ""
    }
}
