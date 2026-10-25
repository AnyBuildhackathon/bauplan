"""Review and prune the learned parts library (agent/data/learned/parts.json, or PAI_LEARNED_PARTS).

    cd agent && uv run python scripts/learned_parts.py list [--category camera] [--estimated]
    cd agent && uv run python scripts/learned_parts.py show web-arducam-b0332
    cd agent && uv run python scripts/learned_parts.py remove web-arducam-b0332
    cd agent && uv run python scripts/learned_parts.py prune --estimated --older-than 90 --unused [--yes]

Every part a build validated on the web or at a distributor is kept there with its sources and the
confidence of each number. `list` shows one line per part, `show` its numbers with their sources,
`remove` drops one part, `prune` drops every part matching all the given conditions (a dry run
unless --yes).
"""

from __future__ import annotations

import argparse
import json
import sys

from pai_agent import learned_parts


def _line(part: dict) -> str:
    estimated = part.get("estimated") or []
    label = part.get("confidence") or "sourced"
    if estimated:
        label += " (" + ", ".join(estimated) + ")"
    hosts = sorted({s.get("distributor") or s["url"].split("/")[2] for s in part.get("sources") or [] if s.get("url")})
    return (
        f"{part['id']:<44} {part.get('category', ''):<18} {label:<28} used {int(part.get('used') or 0):>2}  "
        f"checked {part.get('checked', '?')}  {', '.join(hosts) or part.get('shop', '')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and prune the learned parts library.")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="one line per learned part")
    listing.add_argument("--category")
    listing.add_argument("--estimated", action="store_true", help="only parts with estimated numbers")
    show = sub.add_parser("show", help="a part's numbers with their sources")
    show.add_argument("id")
    remove = sub.add_parser("remove", help="drop one part")
    remove.add_argument("id")
    prune = sub.add_parser("prune", help="drop the parts matching every given condition")
    prune.add_argument("--estimated", action="store_true", help="parts with estimated numbers")
    prune.add_argument("--older-than", type=int, metavar="DAYS", help="checked more than DAYS days ago")
    prune.add_argument("--unused", action="store_true", help="never picked in a build")
    prune.add_argument("--yes", action="store_true", help="remove them; without it only list them")
    args = parser.parse_args(argv)

    print("Library: " + str(learned_parts.path()))
    if args.command == "list":
        parts = [p for p in learned_parts.all_parts(args.category) if not args.estimated or p.get("confidence") == "estimated"]
        for part in parts:
            print(_line(part))
        print(str(len(parts)) + " part(s)")
        return 0
    if args.command == "show":
        part = learned_parts.get(args.id)
        if part is None:
            print("No learned part " + args.id, file=sys.stderr)
            return 1
        print(_line(part))
        print(part["name"] + (" · " + part["manufacturer"] + " " + part["mpn"] if part.get("mpn") else ""))
        for name, meta in sorted((part.get("fields") or {}).items()):
            value = part.get(name, (part.get("bench") or {}).get(name.replace("bench_", ""), ""))
            where = meta.get("source") or meta.get("basis") or "computed from " + ", ".join(meta.get("from") or [])
            print(f"  {name:<20} {json.dumps(value):<14} {meta.get('confidence', ''):<10} {where}")
        print("  price " + f"{part.get('unit_price_eur')} EUR" + (" (" + str(part.get("shop_price")) + " " + str(part.get("shop_currency")) + ")" if part.get("shop_currency") not in (None, "EUR") else "") + " at " + str(part.get("url")))
        for source in part.get("sources") or []:
            print("  source " + source.get("kind", "") + ": " + source["url"] + " (" + (source.get("manufacturer") or "") + " " + (source.get("mpn") or "") + ")")
        return 0
    if args.command == "remove":
        if learned_parts.remove(args.id):
            print("Removed " + args.id)
            return 0
        print("No learned part " + args.id, file=sys.stderr)
        return 1
    if not (args.estimated or args.older_than is not None or args.unused):
        print("Give at least one of --estimated, --older-than, --unused.", file=sys.stderr)
        return 2
    ids = learned_parts.prune(args.estimated, args.older_than, args.unused, dry_run=not args.yes)
    for part_id in ids:
        part = learned_parts.get(part_id)
        print(_line(part) if part else part_id)
    print(str(len(ids)) + " part(s) " + ("removed." if args.yes else "would be removed; add --yes to remove them."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
