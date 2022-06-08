//  creates color value from hue, saturation, brightness, alpha
function _hsla(h, s, b, a) {
    var lightness = (2 - s)*b
    var satHSL = s*b/((lightness <= 1) ? lightness : 2 - lightness)
    lightness /= 2
    var c = Qt.hsla(h, satHSL, lightness, a)
    colorChanged(c)
    return c
}

// create rgb value
function _rgb(rgb, a) {
    var c = Qt.rgba(rgb.r, rgb.g, rgb.b, a)
    colorChanged(c)
    return c
}

//  creates a full color string from color value and alpha[0..1], e.g. "#FF00FF00"
function _fullColorString(clr, a) {
    return "#" + ((Math.ceil(a*255) + 256).toString(16).substr(1, 2) + clr.toString().substr(1, 6)).toUpperCase()
}

//  extracts integer color channel value [0..255] from color value
function _getChannelStr(clr, channelIdx) {
    return parseInt(clr.toString().substr(channelIdx*2 + 1, 2), 16)
}

// set color from outside
function setColor(color) {
    // color object
    var c = Qt.tint(color, "transparent")
    console.debug('set_color is called with:'+c)
    // set rgb. Now it's insufficient to update hue related component.
    colorPicker.colorValue = c
}

// As defined in WCAG 2.1
var relativeLuminance = function (R8bit, G8bit, B8bit) {
  var RsRGB = R8bit / 255.0;
  var GsRGB = G8bit / 255.0;
  var BsRGB = B8bit / 255.0;

  var R = (RsRGB <= 0.03928) ? RsRGB / 12.92 : Math.pow((RsRGB + 0.055) / 1.055, 2.4);
  var G = (GsRGB <= 0.03928) ? GsRGB / 12.92 : Math.pow((GsRGB + 0.055) / 1.055, 2.4);
  var B = (BsRGB <= 0.03928) ? BsRGB / 12.92 : Math.pow((BsRGB + 0.055) / 1.055, 2.4);

  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
};

function blackContrast(r, g, b) {
  var L = relativeLuminance(r, g, b);
  return (L + 0.05) / 0.05;
};

function whiteContrast(r, g, b) {
  var L = relativeLuminance(r, g, b);
  return 1.05 / (L + 0.05);
};

function autoTextColor(r, g, b) {
  var prefer = "#ffffff"
  var Cb = blackContrast(r * 255, g * 255, b * 255);
  var Cw = whiteContrast(r * 255, g * 255, b * 255);
  console.log(Cb, Cw)
  if(Cb >= 7.0 && Cw >= 7.0) return prefer;
  else return (Cb > Cw) ? '#000000' : '#ffffff'
}
