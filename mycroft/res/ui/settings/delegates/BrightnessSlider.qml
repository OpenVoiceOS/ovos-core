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

Slider {
    id: control
    from: 0.75
    to: 1.15
    live: true
    stepSize: 0.1
    orientation: Qt.Vertical
    value: 1

    background: Rectangle {
        x: control.leftPadding + control.availableWidth / 2 - width / 2
        y: control.topPadding
        implicitWidth: 40
        implicitHeight: 200
        width: implicitWidth
        height: control.availableHeight
        radius: 2
        color: Kirigami.Theme.textColor

        Rectangle {
            width: parent.width
            height: control.visualPosition * parent.height
            color: Qt.darker(Kirigami.Theme.textColor, 2.5)
            radius: 2
        }
    }

    handle: Rectangle {
        y: control.topPadding + control.visualPosition * (control.availableHeight - height)
        x: control.leftPadding + control.availableWidth / 2 - width / 2
        width: parent.width
        height: 8
        color: control.pressed ? Kirigami.Theme.highlightColor : Kirigami.Theme.backgroundColor
        border.color: Kirigami.Theme.highlightColor
    }
}
