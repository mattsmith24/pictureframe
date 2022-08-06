# pictureframe

A quick and dirty python program that displays the status of a Fronius PV inverter
using a fullscreen image with some overlay text. The intention is to display this on 
a TV or monitor that is visible in the house as both a pleasant digital pictureframe
and also informational solar panel usage. It could be run on a Rasberry PI although
it hasn't yet been tested on that hardware.

Required python modules:
pygame
requests
Pillow
beautifulsoup4

Configuration is via a solarweb.json file with the following format:

{
  "username": "your solarweb username (email)",
  "password": "your solarweb password"
}

Images are not distributed with this software so you will need to download your own
for the images subfolder (see the README files for suggestions)
