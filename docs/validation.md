# How close the drone simulation is to real drones

The MuJoCo missions (`agent/src/pai_agent/mission_sim.py`) and the physics card (`agent/src/pai_agent/flight.py`) fly one power train, `agent/src/pai_agent/plant.py`.
This page says what that model contains, where each number comes from, and how far its results are from published real-world figures.
`agent/tests/test_validation.py` recomputes the table and fails when any error leaves its bound.
To refresh the table after a model change, run `cd agent && uv run python scripts/validation_table.py`.

## What the model contains

- **Propeller thrust from measured curves.**
  Thrust and power coefficients against advance ratio come from the [UIUC propeller database, volume 2](https://m-selig.ae.illinois.edu/props/volume-2/propDB-volume-2.html): eight small props (GWS 2.5x1, 3x2, 3x3, 4x2.5, 4x4, 4.5x3, APC Free Flight 4.2x4, Micro Invent 4.3x3.5 3-blade), each at the highest rpm tested.
  The chosen prop takes the documented prop with the same blade count first, then the nearest pitch-to-diameter ratio, stretched along J by the ratio of the two.
  Every 3-blade prop in the library uses the Micro Invent 4.3x3.5 curve; the 4-blade Gemfan 2020 has no 4-blade curve and uses the nearest 2-blade one (GWS 3x3), and the physics card says so.
  The maker's 100 % load-table row sets the level of the curve, so the static thrust is the published one.
- **Motor.**
  A DC motor with back EMF from its KV and a winding resistance fitted so the 100 % row comes out at its published rpm, voltage and current.
  The motor and the prop settle where their torques meet, so the prop spins up as it unloads at speed.
  The static power at each thrust is the maker's load table; the model adds how it changes with airspeed.
- **Battery sag and drain.**
  Open-circuit voltage against charge from Chen and Rincón-Mora (IEEE Transactions on Energy Conversion 21(2), 2006), scaled to 4.35 V full for LiHV.
  Internal resistance per cell is 0.326 V over the rated current (C rating times capacity).
  That figure comes from a 4S 1300 mAh 75C pack measured at 3.34 mOhm per cell ([drone-zone.de review](https://drone-zone.de/battery-review-drone-lab-chaos-edition-4s-1300-mah-75-150c)).
  The terminal voltage follows the current actually drawn, the charge drains with it, and full-throttle thrust and the prop's zero-thrust speed follow the sagging voltage.
  Flight times end at 80 % of the capacity or at 3.3 V per cell under load, whichever comes first.
  The card shows the top speed on a fresh pack and `top_speed_end_kmh` at the end of a full-speed flight.
- **Ground effect.**
  Cheeseman and Bennett (ARC R&M 3021, 1955): thrust times 1 / (1 - (R / 4z)^2).
  The hold flies at 1.5 m, where it adds 0.002 % for a 51 mm prop, so ground effect does not change any mission result.
- **Chase sensing.**
  The drone sees each fly only through its camera: the camera's field of view (165° for the Caddx Ant, 160° for the C03, C04 and Ratel, from their pages), its uptilt (20° assumed), and the NTSC picture digitised at 720 x 480 pixels and 30 frames per second.
  A 6 mm fly is detected while it covers 2 pixels, the Johnson criterion for detection at 50 % probability, and while it is inside the view.
  With these cameras that puts the detection range at 0.9 to 1.0 m.
  Each fix is late by the camera's latency (8 ms for the Ratel; 20 ms assumed where none is published), one frame, and a 15 ms detector pass, about 68 ms in all.
  Each fix also carries half a pixel of noise in bearing and in apparent size.
  The fixes feed a constant-velocity Kalman filter that predicts across the delay.
  A track coasts 0.5 s without a fix; then the drone stops and turns on the spot to search.
  The chase reports `detect_range_m`, `sensing_delay_ms`, `first_fix_s`, `reacquire_s` and `tracks_lost`.

Still not modelled: prop wash between rotors, the vortex ring state, motor heating, and the drone's own sensor noise (it knows its own position and attitude exactly).
No chase number has been compared with a real fly-catching flight, because none is published.

## Where it runs

Everything runs on the CPU: MuJoCo in Python on the backend and MuJoCo WASM in the browser.
The accuracy comes from what the model contains (the measured curves, the sag, the sensing), not from the processor.
A GPU (NVIDIA Isaac Sim and Isaac Lab, wired as an optional remote host in `agent/src/pai_agent/tools/isaac.py`) would run many more flights in parallel for training; it would not make one flight more accurate.

## Published numbers against ours

Maker "up to" flight times are compared with the hover time.
A reviewer's hard-flown time must fall inside the band from full speed to hover; that band is wide, so those rows only check that the number is possible.
The 5-inch rows compare a library build with figures for its class, not the same parts.
No published top speed for the Air75 II was found.

<!-- validation-table:start -->
| Drone | Number | Pack | Published | Ours | Ours is | Error | Bound | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Air75 II Freestyle | flight time | BetaFPV LAVA II 1S 480mAh 95C | 7.5 min | 7.8 min | hover, plant (core card 7.5 min) | +4.0 % | ±8 % | [BetaFPV: up to 7:30 on LAVA II 1S 480 mAh](https://betafpv.com/products/air75-ii-brushless-whoop-quadcopter) |
| Air75 II Champion | flight time | BetaFPV LAVA II 1S 480mAh 95C | 6.83 min | 6.6 min | hover, plant (core card 6.3 min) | -3.4 % | ±8 % | [BetaFPV: up to 6:50 on LAVA II 1S 480 mAh](https://betafpv.com/products/air75-ii-brushless-whoop-quadcopter) |
| Air75 II Freestyle | dry weight |  | 21.3 g | 18.1 g | the parts' masses, no pack | -15.0 % | ±18 % | [BetaFPV: 21.3 g without battery](https://betafpv.com/products/air75-ii-brushless-whoop-quadcopter) |
| Meteor75 Pro II | flight time | BetaFPV LAVA II 1S 580mAh 95C | 10.5 min | 9.2 min | hover, plant (core card 8.6 min) | -12.4 % | ±16 % | [BetaFPV: up to 10:30 on LAVA II 1S 580 mAh](https://betafpv.com/products/meteor75-pro-ii-brushless-whoop-quadcopter) |
| Meteor75 Pro II | flight time | BetaFPV LAVA II 1S 680mAh 95C | 11.5 min | 10.0 min | hover, plant (core card 9.5 min) | -13.0 % | ±16 % | [BetaFPV: up to 11:30 on LAVA II 1S 680 mAh](https://betafpv.com/products/meteor75-pro-ii-brushless-whoop-quadcopter) |
| Meteor75 Pro II | flight time | BetaFPV LAVA II 1S 580mAh 95C | 5 min | 0.8 to 9.2 min | full speed to hover | +0.0 % | ±0 % | [Oscar Liang: around 5 min on the 580, flown hard](https://oscarliang.com/betafpv-meteor75-pro-ii-analog/) |
| Meteor75 Pro II | flight time | BetaFPV LAVA II 1S 680mAh 95C | 6 min | 0.9 to 10.0 min | full speed to hover | +0.0 % | ±0 % | [Oscar Liang: around 6 min on the 680, flown hard](https://oscarliang.com/betafpv-meteor75-pro-ii-analog/) |
| Meteor75 Pro II | top speed | BetaFPV LAVA II 1S 580mAh 95C | 85 km/h | 84.6 km/h | card, fresh pack; 80 km/h at the end of the pack; MuJoCo speed run 79 km/h | -0.5 % | ±10 % | [Oscar Liang: estimated top speed around 85 km/h](https://oscarliang.com/betafpv-meteor75-pro-ii-analog/) |
| Meteor75 Pro II | thrust-to-weight | BetaFPV LAVA II 1S 580mAh 95C | 6.33:1 | 6.98:1 | bench thrust over the weight with the pack | +10.3 % | ±13 % | [BetaFPV: 6.33:1 with the LAVA II 580](https://betafpv.com/products/meteor75-pro-ii-brushless-whoop-quadcopter) |
| Meteor75 Pro II | dry weight |  | 27.98 g | 24.1 g | the parts' masses, no pack | -13.9 % | ±18 % | [BetaFPV: 27.98 g](https://betafpv.com/products/meteor75-pro-ii-brushless-whoop-quadcopter) |
| 5-inch 6S freestyle | top speed | BetaFPV LAVA 6S 1100mAh 100C | 150 km/h | 146.3 km/h | card, fresh pack; 138 km/h at the end of the pack; MuJoCo speed run 146 km/h | -2.5 % | ±10 % | [Unmanned Tech: a typical 6S 5-inch freestyle quad reaches roughly 150 km/h](https://www.unmannedtechshop.co.uk/blogs/knowledge-base/fpv-drone-top-speed-how-fast-real-world-by-build-class) |
| 5-inch 6S freestyle | flight time | BetaFPV LAVA 6S 1100mAh 100C | 3 to 5 min | 0.6 to 14.3 min | full speed to hover | +0.0 % | ±0 % | [Unmanned Tech: 3 to 5 min of 5-inch freestyle on a 4S 1300 (the 6S 1100 holds 27 % more energy)](https://www.unmannedtechshop.co.uk/blogs/knowledge-base/fpv-drone-flight-time-how-to-get-more-minutes-in-the-air) |

| Motor | Prop | Throttle rows: published g / ours g (error) | Mean error 50 to 100 % | Bound |
| --- | --- | --- | --- | --- |
| [BetaFPV 0802 Freestyle 22000KV (2026)](https://betafpv.com/products/0802-brushless-motors-2026) | Gemfan 1614 40 mm 3-blade | 20%: 2.3/4.4 (+91 %), 30%: 7.1/8.4 (+18 %), 40%: 12.4/13 (+5 %), 50%: 18/18.1 (+0 %), 60%: 24/23.5 (-2 %), 70%: 29.9/29.3 (-2 %), 80%: 36.3/35.2 (-3 %), 90%: 41.7/41.4 (-1 %), 100%: 47.7/47.7 (-0 %) | 1.4 % | 12 % |
| [BetaFPV 0802 Champion 28000KV (2026)](https://betafpv.com/products/0802-brushless-motors-2026) | Gemfan 1614 40 mm 3-blade | 20%: 4.1/6 (+45 %), 30%: 10/11 (+10 %), 40%: 17.2/16.8 (-2 %), 50%: 24.2/23 (-5 %), 60%: 31/29.6 (-5 %), 70%: 38.5/36.4 (-5 %), 80%: 45.7/43.5 (-5 %), 90%: 51.8/50.8 (-2 %), 100%: 58.2/58.2 (-0 %) | 3.6 % | 12 % |
| [BetaFPV 1102 21000KV (2026)](https://betafpv.com/products/1102-brushless-motors-2026) | Gemfan 1811 45 mm 3-blade | 30%: 9.6/11.5 (+20 %), 40%: 16.7/17.9 (+7 %), 50%: 24.8/25 (+1 %), 60%: 34.1/32.6 (-4 %), 70%: 42.4/40.7 (-4 %), 80%: 50.2/49 (-2 %), 90%: 58.5/57.7 (-1 %), 100%: 66.6/66.6 (+0 %) | 2.2 % | 12 % |
| [BetaFPV 1103 10500KV (2S)](https://betafpv.com/products/1103-brushless-motors-aquila20) | Gemfan 2218 56 mm 3-blade | 20%: 11/13.3 (+21 %), 30%: 26/25.2 (-3 %), 40%: 42/39 (-7 %), 50%: 60/54.2 (-10 %), 60%: 80/70.3 (-12 %), 70%: 97/87.3 (-10 %), 80%: 113/105 (-7 %), 90%: 128/123.3 (-4 %), 100%: 142/142 (-0 %) | 7.1 % | 12 % |
| [BetaFPV LAVA 1104 7200KV](https://betafpv.com/products/lava-series-1104-brushless-motors) | Gemfan D2.2 56 mm 3-blade | 30%: 31/28.7 (-7 %), 40%: 48/48.1 (+0 %), 50%: 74/71 (-4 %), 60%: 100/96.9 (-3 %), 70%: 139/125.6 (-10 %), 80%: 168/156.7 (-7 %), 90%: 186/189.9 (+2 %), 100%: 225/225 (-0 %) | 4.3 % | 12 % |
| [BetaFPV LAVA 1104 5500KV](https://betafpv.com/products/lava-series-1104-brushless-motors) | Gemfan D2.2 56 mm 3-blade | 30%: 29/29.9 (+3 %), 40%: 58/50 (-14 %), 50%: 82/73.8 (-10 %), 60%: 105/100.8 (-4 %), 70%: 137/130.7 (-5 %), 80%: 163/163 (-0 %), 90%: 192/197.5 (+3 %), 100%: 234/234 (-0 %) | 3.6 % | 12 % |
| [BetaFPV Snow 2306 1860KV](https://betafpv.com/products/snow-2306-brushless-motors) | Gemfan 51466 MCK V2 5-inch 3-blade | 30%: 35/215.7 (+516 %), 40%: 195/353.2 (+81 %), 50%: 375/512.5 (+37 %), 60%: 611/689.9 (+13 %), 70%: 836/882.7 (+6 %), 80%: 1114/1088.7 (-2 %), 90%: 1363/1306.3 (-4 %), 100%: 1534/1534 (-0 %) | 10.3 % | 12 % |
| [BetaFPV Snow 2306 2500KV](https://betafpv.com/products/snow-2306-brushless-motors) | Gemfan 51466 MCK V2 5-inch 3-blade | 20%: 93/93.1 (+0 %), 30%: 243/192.1 (-21 %), 40%: 360/316 (-12 %), 50%: 499/460.2 (-8 %), 60%: 600/621.5 (+4 %), 70%: 762/797.3 (+5 %), 80%: 940/985.6 (+5 %), 90%: 1172/1184.9 (+1 %), 100%: 1394/1394 (+0 %) | 3.7 % | 12 % |
<!-- validation-table:end -->

What the table shows:

- **Flight time.**
  The hover time is within 4 % of BetaFPV's Air75 II figures and 12 to 13 % short of its Meteor75 Pro II figures.
- **Top speed.**
  Within 1 % of the reviewer's estimate for the Meteor75 Pro II and 2.5 % under the typical 6S 5-inch figure.
  The MuJoCo speed run is a few km/h below the card on the Meteor75: the run is tilt-limited and the reference attitude loop holds the tilt a few degrees short.
- **Weight.**
  Our parts weigh 14 to 15 % less than the real drones, because the library builds carry no canopy, antenna, wiring or screws.
  The thrust-to-weight comes out 10 % high for the same reason.
- **Motors.**
  The motor and prop model is within 1 to 10 % of the makers' load tables from 50 to 100 % throttle.
  At low throttle it reads high, and most so for the Snow 2306 1860KV, whose table has 35 g at 30 % throttle.
