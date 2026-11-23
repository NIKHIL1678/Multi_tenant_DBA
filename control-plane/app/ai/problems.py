"""Explain: which specialists look at each problem the server page shows.

The ids are those of dashboard/src/features/datasources/server/attention.ts. Explain needs no
planning call: the problem decides the specialists, so it is faster and cheaper than chat.
An unknown id is refused (the dashboard and this table are kept in step by a test).
"""

from app.models.enums import Specialist

H, Q, S = Specialist.HEALTH, Specialist.QUERY, Specialist.SCHEMA

PROBLEMS: dict[str, tuple[Specialist, ...]] = {
    "lockwaits": (H,),
    "longtrx": (H,),
    "connections": (H,),
    "cache": (H, Q),
    "lag": (H,),
    "deadlocks": (H, Q),
    "noindex": (Q, S),
    "slowest": (Q,),
    "slowlog": (Q,),
    "pglog": (Q,),
    "fullscans": (S, Q),
    "invalid": (S,),
    "fk": (S,),
    "pk": (S,),
    "dupes": (S,),
    "unused": (S,),
    "reclaim": (S,),
    "dead": (S,),
}


def explain_question(title: str) -> str:
    return f"Explain this problem in plain words, why it matters and what to do: {title}"
