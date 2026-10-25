"""Recompute the validation table and write it into docs/validation.md between its markers."""

from __future__ import annotations

from pathlib import Path

from pai_agent.validation import build_rows, markdown, motor_rows

DOC = Path(__file__).resolve().parents[2] / "docs" / "validation.md"
START = "<!-- validation-table:start -->"
END = "<!-- validation-table:end -->"


def main() -> None:
    table = markdown(build_rows(), motor_rows())
    text = DOC.read_text()
    head, rest = text.split(START, 1)
    _old, tail = rest.split(END, 1)
    DOC.write_text(head + START + "\n" + table + END + tail)
    print(table)


if __name__ == "__main__":
    main()
