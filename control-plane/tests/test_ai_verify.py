"""The SQL allow-list and evidence checks of the Verifier, statement by statement."""

import pytest

from app.ai import facts
from app.ai.verify import check_statement
from tests.ai_fakes import INDEXES, QUERIES, TABLES


def evidence() -> facts.Evidence:
    ev = facts.Evidence()
    facts.add_tables(ev, TABLES, set())
    facts.add_indexes(ev, INDEXES, {"hrm.attendance"})
    facts.add_queries(ev, QUERIES, {"hrm.attendance"})
    return ev


Q1 = ["Q1"]  # the attendance statement: uses emp_id and day


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX idx_att_emp_day ON hrm.attendance (emp_id, day)",
        "create index idx_att_emp_day on `hrm`.`attendance` (`emp_id`, `day`);",
        "CREATE INDEX idx_att_emp_day ON hrm.attendance (emp_id, day DESC)"
        " ALGORITHM=INPLACE LOCK=NONE",
        "CREATE INDEX idx_att_emp ON hrm.attendance (emp_id(10))",
        "DROP INDEX idx_status ON hrm.attendance",
        "ANALYZE TABLE hrm.attendance",
        "OPTIMIZE TABLE hrm.attendance",
    ],
)
def test_mysql_allowed(sql: str) -> None:
    action, why = check_statement(sql, "mysql", evidence(), Q1)
    assert action is not None, why
    assert action.table == "hrm.attendance"


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DROP TABLE hrm.attendance", "not allowed"),
        ("UPDATE hrm.attendance SET status = 1", "not allowed"),
        ("DELETE FROM hrm.attendance", "not allowed"),
        ("TRUNCATE hrm.attendance", "not allowed"),
        ("ALTER TABLE hrm.attendance ADD INDEX i (emp_id)", "not allowed"),
        ("GRANT ALL ON *.* TO x", "not allowed"),
        ("CREATE UNIQUE INDEX i ON hrm.attendance (emp_id)", "not allowed"),
        (
            "CREATE INDEX i ON hrm.attendance (emp_id); DROP TABLE hrm.attendance",
            "one plain statement",
        ),
        ("CREATE INDEX i ON hrm.attendance (emp_id) -- ok", "one plain statement"),
        ("CREATE INDEX i ON hrm.attendance (emp_id) /* x */", "one plain statement"),
        ("ANALYZE TABLE hrm.attendance # x", "one plain statement"),
        ("CREATE INDEX i ON hrm.attendance ((CONCAT(emp_id, 'x')))", "one plain statement"),
        ("CREATE INDEX i ON hrm.ghost (emp_id)", "not on this server"),
        ("CREATE INDEX i ON hrm.attendance (salary)", "not in the evidence"),
        ("CREATE INDEX idx_status ON hrm.attendance (emp_id)", "already exists"),
        ("DROP INDEX idx_nope ON hrm.attendance", "no index idx_nope"),
        ("DROP INDEX `PRIMARY` ON hrm.attendance", "primary key"),
        ("CREATE INDEX CONCURRENTLY i ON hrm.attendance (emp_id)", "not allowed"),
        ("", "empty"),
    ],
)
def test_mysql_refused(sql: str, reason: str) -> None:
    action, why = check_statement(sql, "mysql", evidence(), Q1)
    assert action is None
    assert why is not None and reason in why


def pg_evidence() -> facts.Evidence:
    ev = evidence()
    ev.know_index("public", "orders", "orders_status_idx", ["status"])
    ev.columns["public.orders"].update({"customer_id", "created_at"})
    return ev


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX CONCURRENTLY orders_customer_idx ON public.orders (customer_id, created_at)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_idx"
        ' ON "public"."orders" USING btree (customer_id)',
        "DROP INDEX CONCURRENTLY public.orders_status_idx",
        "DROP INDEX CONCURRENTLY IF EXISTS orders_status_idx",
        "ANALYZE public.orders",
        "VACUUM (ANALYZE) public.orders",
        "REINDEX INDEX CONCURRENTLY public.orders_status_idx",
    ],
)
def test_postgres_allowed(sql: str) -> None:
    action, why = check_statement(sql, "postgres", pg_evidence(), [])
    assert action is not None, why
    assert action.table == "public.orders"


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("CREATE INDEX orders_customer_idx ON public.orders (customer_id)", "not allowed"),
        ("DROP INDEX public.orders_status_idx", "not allowed"),
        ("VACUUM FULL public.orders", "not allowed"),
        ("REINDEX TABLE public.orders", "not allowed"),
        ("DROP INDEX CONCURRENTLY public.nope_idx", "no index"),
        ("CREATE INDEX CONCURRENTLY i ON public.orders USING hash (customer_id)", "not allowed"),
        ("COPY public.orders TO '/tmp/x'", "one plain statement"),
    ],
)
def test_postgres_refused(sql: str, reason: str) -> None:
    action, why = check_statement(sql, "postgres", pg_evidence(), [])
    assert action is None
    assert why is not None and reason in why


def test_a_bare_table_name_uses_the_findings_schema() -> None:
    action, _ = check_statement(
        "ANALYZE TABLE attendance", "mysql", evidence(), Q1, default_schema="hrm"
    )
    assert action is not None and action.table == "hrm.attendance"
