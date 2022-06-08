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
    id: item
    property color palettsColor : "transparent"

    onPalettsColorChanged: {
        createThemeView.selectedPrimaryColor = palettsColor
    }

    implicitHeight: grid.height
    implicitWidth: grid.width

    GridLayout {
        id: grid
        columns: 4
        anchors.fill: parent

        ButtonGroup {
            id: group
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#000000"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#1A1A1A"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#012010"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#200A22"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#0D0D22"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#221D1A"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#242411"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#0c1821"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#0d1701"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#280607"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#170d01"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }

        Palette {
            ButtonGroup.group: group
            target_color: "#0c0117"
            onCheckedChanged: {
                if(checked) {
                    item.palettsColor = target_color
                }
            }
        }
    }
}
