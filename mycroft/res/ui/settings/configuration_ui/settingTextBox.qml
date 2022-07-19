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

import QtQuick 2.9
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.4
import org.kde.kirigami 2.11 as Kirigami

TextField {
    property string buttonId;
    property var modelData;
    property var key;
    property var value;
    signal fieldUpdated(var modelData, string key, string value);
    Layout.fillWidth: true
    Layout.minimumHeight: Kirigami.Units.gridUnit * 2
    
    onTextChanged: {
        fieldUpdated(modelData, key, text)
    }
}
