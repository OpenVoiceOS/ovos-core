import QtQuick.Layouts 1.12
import QtQuick 2.12
import QtQuick.Controls 2.12
import org.kde.kirigami 2.11 as Kirigami

import Mycroft 1.0 as Mycroft

Mycroft.Delegate {
    id: systemInputBoxFrame
    property var title: sessionData.title
    property var placeholderText: sessionData.placeholder
    property var confirmButtonText: sessionData.confirm_text
    property var exitButtonText: sessionData.exit_text
    property var skillIDHandler: sessionData.skill_id_handler
    property string responseEvent: "input.box.response"
    property string exitEvent: "input.box.close"

    ColumnLayout {
        width: parent.width
        spacing: Kirigami.Units.gridUnit

        Kirigami.Heading {
            level: 2
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            font.bold: true
            text: systemInputBoxFrame.title
            color: Kirigami.Theme.textColor
        }

        TextField {
            id: txtField
            Kirigami.Theme.colorSet: Kirigami.Theme.View
            Layout.fillWidth: true
            Layout.leftMargin: Mycroft.Units.gridUnit * 5
            Layout.rightMargin: Mycroft.Units.gridUnit * 5
            Layout.preferredHeight: Mycroft.Units.gridUnit * 4
            placeholderText: systemInputBoxFrame.placeholderText

            onAccepted: {
                triggerGuiEvent(systemInputBoxFrame.responseEvent, {"text": txtField.text})
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignCenter
            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: Mycroft.Units.gridUnit * 5
                text: systemInputBoxFrame.confirmButtonText
                onClicked: {
                    console.log(systemInputBoxFrame.responseEvent)
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../snd/clicked.wav"))
                    triggerGuiEvent(systemInputBoxFrame.responseEvent, {"text": txtField.text})
                }
            }

            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: Mycroft.Units.gridUnit * 5
                text: systemInputBoxFrame.exitButtonText
                onClicked: {
                    Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../snd/clicked.wav"))
                    triggerGuiEvent(systemInputBoxFrame.exitEvent, {})
                }
            }
        }
        Item {
            Layout.fillHeight: true
        }
    }
}
