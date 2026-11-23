"""Finding a table among thousands: families, typos, periods, ambiguity, scale."""

import time
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Collector
from app.schemas.snapshots import TableIndexData
from app.services import snapshots as snapshots_svc
from app.services import table_search as ts
from tests.test_datasources import world

MONTHS = [f"{y}_{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)]


def index(**schemas: Sequence[tuple[str, int | None, int | None]]) -> TableIndexData:
    tables = sum(len(t) for t in schemas.values())
    return TableIndexData.model_validate(
        {
            "total_tables": tables,
            "listed_tables": tables,
            "schemas": [
                {"name": name, "tables": [list(t) for t in rows]} for name, rows in schemas.items()
            ],
        }
    )


HR = index(
    hrm=[(f"attendance_{m}", 1000, 1000 * (i + 1)) for i, m in enumerate(MONTHS)]
    + [("employees", 500, 90_000), ("departments", 20, 8_000), ("leave_requests", 300, 4_000)],
    payroll=[("attendance", 50, 2_000), ("salary_slips", 9000, 900_000)],
    shop=[("orders_p1", 10, 100), ("orders_p2", 10, 100), ("customers", 10, 100)],
)


def test_monthly_tables_are_one_family_with_periods() -> None:
    families = {c.name: c for c in ts.build_candidates(HR) if c.kind == "family"}
    assert set(families) == {"attendance_*", "orders_*"}
    att = families["attendance_*"]
    assert len(att.tables) == 36 and att.tables[0].period == "2024-01"
    assert families["orders_*"].tables[0].period is None, "numbered parts have no period"


def test_two_equally_good_matches_ask_which_one() -> None:
    r = ts.search(HR, "show me the attendance table")
    assert [(m.schema, m.name) for m in r.matches[:2]] == [
        ("hrm", "attendance_*"),
        ("payroll", "attendance"),
    ]
    assert r.ambiguous is True
    assert r.matches[0].kind == "family" and r.matches[0].table_count == 36
    assert r.matches[0].periods == ("2024-01", "2026-12")


def test_a_schema_removes_the_doubt() -> None:
    r = ts.search(HR, "attendance", schema="hrm")
    assert [m.name for m in r.matches] == ["attendance_*"] and r.ambiguous is False


def test_typos_prefixes_and_unrelated_words() -> None:
    assert ts.search(HR, "attendence", schema="hrm").matches[0].name == "attendance_*"
    assert ts.search(HR, "leave", schema="hrm").matches[0].name == "leave_requests"
    r = ts.search(HR, "employee who has the lowest attendance in march", schema="hrm")
    assert r.matches[0].name == "attendance_*"
    assert ts.search(HR, "salary").matches[0].name == "salary_slips"


def test_a_period_prefers_the_family_that_has_it() -> None:
    data = index(
        hrm=[("attendance", 10, 10), ("attendance_2026_10", 1, 1), ("attendance_2026_11", 1, 1)]
    )
    r = ts.search(data, "attendance", period="2026-11")
    assert r.matches[0].name == "attendance_*" and r.ambiguous is False
    assert [t.name for t in r.matches[0].tables] == ["attendance_2026_11"]
    assert ts.search(data, "attendance").ambiguous is True, "without a period it must ask"


def test_a_lone_dated_table_keeps_its_period() -> None:
    data = index(hrm=[("payroll_2026_11", 1, 1), ("salary", 1, 1)])
    single = next(c for c in ts.build_candidates(data) if c.name == "payroll_2026_11")
    assert single.kind == "table" and single.tables[0].period == "2026-11"


def test_weak_ties_are_still_asked() -> None:
    r = ts.search(HR, "employee with the lowest attendance", schema="payroll")
    assert [m.name for m in r.matches] == ["attendance"] and r.ambiguous is False
    data = index(
        hrm=[("attendance", 10, 10), ("attendance_2026_10", 1, 1), ("attendance_2026_11", 1, 1)]
    )
    assert ts.search(data, "employee with the lowest attendance").ambiguous is True


def test_period_picks_the_months_table() -> None:
    r = ts.search(HR, "attendance", schema="hrm", period="2025-03")
    assert [t.name for t in r.matches[0].tables] == ["attendance_2025_03"]
    year = ts.search(HR, "attendance", schema="hrm", period="2026")
    assert len(year.matches[0].tables) == ts.FAMILY_SAMPLE
    assert all(t.period and t.period.startswith("2026") for t in year.matches[0].tables)

    missing = ts.search(HR, "attendance", schema="hrm", period="2027-01")
    assert [t.name for t in missing.matches[0].tables] == ["attendance_2026_12"]
    assert "no table for 2027-01" in missing.notes[0]


def test_nothing_to_search_for() -> None:
    assert ts.search(HR, "show me all the data").matches == []
    assert ts.search(HR, "weather forecast").matches == []
    r = ts.search(HR, "employees", limit=1000)
    assert len(r.matches) <= ts.MAX_RESULTS


def test_names_are_split_into_words() -> None:
    assert ts.words("empAttendance_2024") == ["emp", "attendance", "2024"]
    assert ts.words("HTTPServerLog") == ["http", "server", "log"]
    assert ts.period_of("20240115") == "2024-01-15"
    assert ts.period_of("12") is None and ts.period_of("2024") == "2024"


def test_one_hundred_thousand_tables_stay_fast() -> None:
    big = index(
        **{
            f"tenant_{s}": [(f"attendance_{m}", 100, 100) for m in MONTHS]
            + [(f"module_{s}_{t}_log", 1, 1) for t in range(2464)]
            for s in range(40)
        }
    )
    assert big.listed_tables == 40 * (36 + 2464) == 100_000
    started = time.perf_counter()
    candidates = ts.build_candidates(big)
    r = ts.search(big, "attendance", schema="tenant_7", period="2025-11", candidates=candidates)
    assert time.perf_counter() - started < 5
    assert [t.name for t in r.matches[0].tables] == ["attendance_2025_11"]
    assert r.matches[0].schema == "tenant_7"


def test_truncated_index_is_said() -> None:
    data = HR.model_copy(update={"truncated": True, "total_tables": 90_000})
    assert "biggest" in ts.search(data, "attendance").notes[0]


async def test_loads_the_latest_index_of_the_datasource(db: AsyncSession) -> None:
    w = await world(db)
    with pytest.raises(ts.NoTableIndexError):
        await ts.find_tables(db, w.my_staging.id, "attendance")
    await snapshots_svc.store(db, w.my_staging, Collector.TABLE_INDEX, HR.model_dump(mode="json"))
    r = await ts.find_tables(db, w.my_staging.id, "salary")
    assert r.matches[0].name == "salary_slips"
    with pytest.raises(ts.NoTableIndexError):
        await ts.find_tables(db, uuid.uuid4(), "salary")
