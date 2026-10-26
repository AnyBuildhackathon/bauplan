"""Runs the CAD reference tests and prints one line per part, then every check that failed.

    cd agent && uv run python tests/cad_oracle/run.py              # all parts
    cd agent && uv run python tests/cad_oracle/run.py plate-holes  # some, by name
    cd agent && uv run python tests/cad_oracle/run.py --record     # store measured values for quantities without a formula
    cd agent && uv run python tests/cad_oracle/run.py --keep DIR   # keep the built files in DIR
    cd agent && uv run python tests/cad_oracle/run.py --all-rows   # print every check, not only the failed ones

Offline and without keys. Parts that need FreeCAD or SolidCraft are skipped when the program is missing.
CAD_ORACLE_JOBS (default 4) sets how many parts build at once.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    # Run as a script: import the package the way pytest does, from agent/tests.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cad_oracle import oracle, parts


def main() -> int:
    parser = argparse.ArgumentParser(description="CAD reference tests: build each reference part, measure its files, compare.")
    parser.add_argument("names", nargs="*", help="reference parts to run (default: all)")
    parser.add_argument("--record", action="store_true", help="write the measured values of quantities without a formula to recorded.json")
    parser.add_argument("--keep", type=Path, help="build into this directory and keep the files")
    parser.add_argument("--jobs", type=int, help="parts built at once (default: CAD_ORACLE_JOBS or 4)")
    parser.add_argument("--all-rows", action="store_true", help="print every check, not only the failed ones")
    args = parser.parse_args()

    known = {reference.name: reference for reference in parts.REFERENCES}
    unknown = [name for name in args.names if name not in known]
    if unknown:
        parser.error("unknown reference parts: " + ", ".join(unknown) + ". Known: " + ", ".join(known))
    references = [known[name] for name in args.names] or parts.REFERENCES

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cad-oracle-") as scratch:
        directory = args.keep or Path(scratch)
        directory.mkdir(parents=True, exist_ok=True)
        results = oracle.run(references, directory, args.jobs)
    width = max(len(r.name) for r in references)
    for name, result in results.items():
        if result.skipped:
            status = "skipped: " + result.skipped
        elif result.error:
            status = "FAILED to build"
        else:
            passed = sum(row.ok for row in result.rows)
            status = f"{'ok' if result.ok else 'FAILED'}  {passed}/{len(result.rows)} checks  {result.seconds:5.1f} s"
        print(f"{name:<{width}}  {(result.reference.needs or 'cadquery'):<10}  {status}")
    for name, result in results.items():
        if result.error:
            print(f"\n{name}: the build failed\n{result.error}")
        shown = [row for row in result.rows if args.all_rows or not row.ok]
        if shown:
            print(f"\n{name}: {result.reference.covers}")
            for row in shown:
                print(("   " if row.ok else " x ") + oracle.describe(row))
    if args.record:
        oracle.write_record(results)
        print(f"\nrecorded {sum(r.measured is not None for r in results.values())} parts into {oracle.RECORDED}")
    built = [r for r in results.values() if not r.skipped]
    skipped = len(results) - len(built)
    print(
        f"\n{sum(r.ok for r in built)} of {len(built)} reference parts pass"
        + (f", {skipped} skipped" if skipped else "")
        + f", {time.monotonic() - started:.1f} s"
    )
    return 0 if all(r.ok for r in built) else 1


if __name__ == "__main__":
    sys.exit(main())
