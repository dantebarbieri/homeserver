#!/usr/bin/env python3
"""travel-holidays.py — populate us_holidays for current + next 2 years
with a pto_efficiency annotation per holiday. Deterministic calendar
math, stdlib only. Idempotent via ON CONFLICT."""
import datetime
import sqlite3

DB = "/var/lib/openclaw/state.db"


def nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    """Nth weekday (1-indexed) in month. weekday 0=Mon..6=Sun."""
    d = datetime.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + datetime.timedelta(days=offset + (n - 1) * 7)


def last_weekday(year: int, month: int, weekday: int) -> datetime.date:
    """Last `weekday` (0=Mon..6=Sun) in month."""
    if month == 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    offset = (end.weekday() - weekday) % 7
    return end - datetime.timedelta(days=offset)


def observed(d: datetime.date) -> datetime.date:
    """US federal observance rule: Sat → Fri, Sun → Mon."""
    if d.weekday() == 5:
        return d - datetime.timedelta(days=1)
    if d.weekday() == 6:
        return d + datetime.timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> dict[datetime.date, str]:
    h: dict[datetime.date, str] = {}
    h[observed(datetime.date(year, 1, 1))]   = "New Year's Day"
    h[nth_weekday(year, 1, 0, 3)]            = "MLK Day"
    h[nth_weekday(year, 2, 0, 3)]            = "Presidents Day"
    h[last_weekday(year, 5, 0)]              = "Memorial Day"
    h[observed(datetime.date(year, 6, 19))]  = "Juneteenth"
    h[observed(datetime.date(year, 7, 4))]   = "Independence Day"
    h[nth_weekday(year, 9, 0, 1)]            = "Labor Day"
    h[nth_weekday(year, 10, 0, 2)]           = "Columbus Day"
    h[observed(datetime.date(year, 11, 11))] = "Veterans Day"
    h[nth_weekday(year, 11, 3, 4)]           = "Thanksgiving"
    h[observed(datetime.date(year, 12, 25))] = "Christmas"
    return h


def pto_efficiency(d: datetime.date, all_dates: set[datetime.date]) -> str:
    """free_3day: Mon/Fri. bridge_4day: Tue/Thu. mega_9day: another holiday
    within 7 days. plain: Wed/Sat/Sun."""
    for other in all_dates:
        if other != d and abs((other - d).days) <= 7:
            return "mega_9day"
    wd = d.weekday()
    if wd in (0, 4):
        return "free_3day"
    if wd in (1, 3):
        return "bridge_4day"
    return "plain"


def main() -> int:
    now = datetime.date.today()
    years = [now.year, now.year + 1, now.year + 2]
    per_year = {y: us_federal_holidays(y) for y in years}
    all_dates: set[datetime.date] = set()
    for h in per_year.values():
        all_dates.update(h.keys())

    rows = []
    for y, h in per_year.items():
        for d, name in h.items():
            rows.append((d.isoformat(), name, pto_efficiency(d, all_dates)))

    conn = sqlite3.connect(DB)
    conn.executemany(
        """
        INSERT INTO us_holidays (holiday_date, name, pto_efficiency)
        VALUES (?, ?, ?)
        ON CONFLICT(holiday_date) DO UPDATE SET
          name = excluded.name,
          pto_efficiency = excluded.pto_efficiency
        """,
        rows,
    )
    conn.commit()
    print(f"us_holidays: upserted {len(rows)} rows for {years}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
