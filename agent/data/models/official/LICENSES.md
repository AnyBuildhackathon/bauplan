# Licenses of the official part models

The STEP files in this folder, and the GLB models built from them in `web/public/models/parts/`,
come from the sources below. They are redistributed under their own licenses, not under this
repository's. Three larger Adafruit STEP files (3405, 4062, 5426) are not kept here; the build
downloads them from the same repository into `agent/runs/cache/part-models/`.

## Adafruit CAD Parts

Source: https://github.com/adafruit/Adafruit_CAD_Parts (commit c128bceb, checked 2026-10-25)

Files: `1904-micro-lipo-charger.step`, `2472-bno055-breakout.step`, `3777-tt-motor.step`,
`328-lipo-2500mah.step`, `2011-li-ion-2000mah.step`, `353-li-ion-6600mah.step`; GLBs for
3405, 4062, 5426, 1904, 2472, 3777, 328, 2011 and 353.

```
MIT License

Copyright (c) 2016 Adafruit Industries

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## KiCad 3D models library

Source: https://gitlab.com/kicad/libraries/kicad-packages3D (commit 89757151, checked 2026-10-25),
`Module.3dshapes/RaspberryPi_Pico.step` and `RaspberryPi_Pico_W.step` by Peter S. Hollander,
contributed to the KiCad library.

Files: `RaspberryPi_Pico.step`, `RaspberryPi_Pico_W.step`; GLBs `adafruit-4883-pico.glb`, `pico-w.glb`.

License: Creative Commons Attribution-ShareAlike 4.0 (https://creativecommons.org/licenses/by-sa/4.0/legalcode),
with the KiCad library exception: "To the extent that the creation of electronic designs that use
'Licensed Material' can be considered to be 'Adapted Material', then the copyright holder waives
article 3 of the license with respect to these designs and any generated files which use data
provided as part of the 'Licensed Material'." These two files, and the GLBs converted from them,
stay under CC-BY-SA 4.0. See https://www.kicad.org/libraries/license/.
