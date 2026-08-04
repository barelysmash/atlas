from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Metric:
    """A single measured quantity.

    Mirrors the metric shape in JAM's observation and insight schemas. The
    optional fields are optional there too: a raw reading carries a name and a
    value, and gains a unit, a delta, or a period only when it has one.

    ``period`` is an ISO 8601 duration such as P4W, describing the window the
    value covers. It is not a label like "2026-06"; those belong in an
    Observation's ``source_ref``.
    """

    name: str
    value: float
    unit: str | None = None
    delta: float | None = None
    period: str | None = None
