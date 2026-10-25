"""The simulation and the physics card against published real-world numbers: every error stays inside the bound docs/validation.md reports."""

from pathlib import Path

import pytest

from pai_agent.validation import build_rows, markdown, motor_rows

DOC = Path(__file__).resolve().parents[2] / "docs" / "validation.md"


@pytest.fixture(scope="module")
def tables():
    return build_rows(), motor_rows()


def test_every_published_number_is_within_its_bound(tables):
    rows, _motors = tables
    for row in rows:
        assert abs(row["error_pct"]) <= row["bound_pct"], row["drone"] + " " + row["what"] + ": " + str(row["error_pct"]) + " %"
        assert row["url"].startswith("https://")


def test_motor_thrust_follows_the_makers_load_tables(tables):
    _rows, motors = tables
    for motor in motors:
        assert motor["mean_error_pct"] <= motor["bound_pct"], motor["motor"]
        # The 100 % row is where the motor is fitted: it matches.
        assert motor["rows"][-1][3] == pytest.approx(0.0, abs=0.5)


def test_the_docs_table_is_the_one_the_model_gives(tables):
    rows, motors = tables
    assert markdown(rows, motors) in DOC.read_text(), "docs/validation.md is stale: run scripts/validation_table.py"
