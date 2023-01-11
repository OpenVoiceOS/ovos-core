import QtQuick 2.9

MouseArea {
    id: mouseSwipeArea
    preventStealing: true

    property real prevX: 0
    property real prevY: 0
    property real velocityX: 0.0
    property real velocityY: 0.0
    property int startX: 0
    property int startY: 0
    property bool tracing: false

    signal swipe(string direction)

    onPressed: {
        startX = mouse.x
        startY = mouse.y
        prevX = mouse.x
        prevY = mouse.y
        velocityX = 0
        velocityY = 0
        tracing = true
    }

    onPositionChanged: {
        if ( !tracing ) return
        var currVelX = (mouse.x-prevX)
        var currVelY = (mouse.y-prevY)

        velocityX = (velocityX + currVelX)/2.0;
        velocityY = (velocityY + currVelY)/2.0;

        prevX = mouse.x
        prevY = mouse.y

        if ( velocityX > 15 && mouse.x > mouseSwipeArea.width * 0.25 ) {
            tracing = false
            mouseSwipeArea.swipe("right")
        } else if ( velocityX < -15 && mouse.x < mouseSwipeArea.width * 0.75 ) {
            tracing = false
            mouseSwipeArea.swipe("left")
        } else if (velocityY > 15 && mouse.y > mouseSwipeArea.height * 0.25 ) {
            tracing = false
            mouseSwipeArea.swipe("down")
        } else if ( velocityY < -15 && mouse.y < mouseSwipeArea.height * 0.75 ) {
            tracing = false
            mouseSwipeArea.swipe("up")
        }
    }
}
