# pictureframe

A python program that displays the status of a Fronius PV inverter
using a fullscreen image with some overlay text. The intention is to display this on 
a TV or monitor that is visible in the house as both a pleasant digital pictureframe
and also informational solar panel usage. It could be run on a Rasberry PI although
it hasn't yet been tested on that hardware.

Required python modules:

- pygame
- requests
- Pillow
- beautifulsoup4

Configuration is via a solarweb.json file with the following format:

```json
{
  "username": "your solarweb username (email)",
  "password": "your solarweb password",
  "grid_threshold": 1000
}
```

grid_threshold is the number of Watts that is exceeded by the grid power draw before
the program will start displaying pictures from the "grid" folder. The idea is to
alert / inform the household when a certain amount of power is being used.

Images are not distributed with this software so you will need to download your own
for the images subfolder (see the README files for suggestions)

To run it, try `python main.py`.

There is an optional script to download solar history to csv files (per year). To use
this script. First add a field 'install_date' to the solarweb.json file with format 
'YYYY-MM-DD'. The script will attempt to download daily data from the date until now.
To run it type `python getallcsv.py`. It will outpout files to logcsv-{year}.csv
files.
