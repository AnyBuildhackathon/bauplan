"""Standard parts in printed parts: screws, nuts, washers and heat-set inserts with the holes they need.

A printed part lists its standard parts as `fasteners` (in its product spec part or in cad_part's
arguments): kind, standard, size, where each one sits and which hole it gets. The bill of materials
then names each by its standard, size and length.

- `fasteners.py` is SOMA's standard-parts module (https://github.com/Kai-Jungsthoefel/SOMA), copied under
  the Apache-2.0 option of its `GPL-3.0-or-later OR Apache-2.0` license; its header lists what AnyBuild
  changed. It builds each part without thread in CadQuery, with its clearance, tap, insert or nut-trap hole.
- `data/` holds its dimension tables, unchanged from bd_warehouse (Apache-2.0, see `data/README.md`).
- `hardware.py` is AnyBuild's own: it checks the entries against those tables, builds them, hands them to
  the FreeCAD harness as STEP files (the sandboxed part script cannot import CadQuery), and prices them
  for the bill of materials through the catalog search.
"""
