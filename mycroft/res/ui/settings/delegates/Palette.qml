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

Button {
    id: control
    property color target_color : "#21be2b"
    property color border_color : Kirigami.Theme.textColor
    property color selected_border_color : Kirigami.Theme.highlightColor
    Layout.fillWidth: true
    Layout.fillHeight: true
    checkable: true

    onCheckedChanged: {
        if(checked) {
            Mycroft.SoundEffects.playClickedSound(Qt.resolvedUrl("../../../snd/clicked.wav"))
        }
    }

    background: Rectangle {
        border.color: (checked ? selected_border_color : border_color)
        border.width: 4
        radius: 3

        Rectangle {
            anchors.fill: parent
            anchors.margins: 4
            radius: 2
            color: target_color
        }
    }
}
