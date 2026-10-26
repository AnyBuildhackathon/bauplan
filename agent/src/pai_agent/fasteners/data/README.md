# Dimension tables for standard parts

The CSV files in this folder are unchanged copies of the tables in [bd_warehouse](https://github.com/gumyr/bd_warehouse) by Roger Maitland (gumyr), folder `src/bd_warehouse/data/`, at commit `eed2da118da99007ad2d3904466ac0b24964f84d` of 2026-09-21.
They are licensed under the Apache License 2.0 ("Copyright 2024 Gumyr"); the license text is in `LICENSE-bd_warehouse.txt`.
`../fasteners.py`, taken from SOMA, reads them, and `../hardware.py` builds AnyBuild's standard parts with it.

| File | What it holds |
| --- | --- |
| `socket_head_cap_parameters.csv` | Socket head cap screws, ISO 4762 |
| `button_head_parameters.csv` | Button head screws, ISO 7380-1 |
| `countersunk_head_parameters.csv` | Countersunk screws, ISO 10642 (its other standards are not used) |
| `hex_head_parameters.csv` | Hex head screws and bolts, ISO 4017, ISO 4014 and DIN 931 |
| `setscrew_parameters.csv` | Set screws with a flat point, ISO 4026 |
| `hex_nut_parameters.csv` | Hex nuts, ISO 4032, ISO 4033 and ISO 4035 |
| `square_nut_parameters.csv` | Square nuts, DIN 557 |
| `plain_washer_parameters.csv` | Plain washers, ISO 7089, ISO 7091 and ISO 7093 |
| `clearance_hole_sizes.csv` | Clearance holes; the columns Close, Normal and Loose are the fine, medium and coarse series of ISO 273 |
| `tap_hole_sizes.csv` | Tap drill holes (the column Soft is used) |
| `nominal_screw_lengths.csv` | The standard lengths of each screw standard |
| `heatset_nut_parameters.csv` | Heat-set inserts by ruthex, CNC Kitchen, McMaster-Carr, Hilitchi and AE-SamZhihui |
| `drill_sizes.csv` | The inch number and letter drills that the insert table gives as holes |

What to know about the data:

- Some values are nominal sizes and some are the largest allowed; the head of ISO 4762 M3, for example, is 5.68 mm across, its largest size with knurling.
- The insert holes are inch drills and differ a little from round metric values: the short ruthex M3 insert (M3x4) gets drill #21, 4.04 mm.
- For the M10 inserts of ruthex and CNC Kitchen the table gives "M14" as the drill, more than the insert's own diameter; `fasteners.py` refuses those inserts with a message.
- ISO 4035 M3 is listed under a 0.45 mm pitch instead of 0.5 mm; without threads only the diameter counts, so `fasteners.py` uses that row.
