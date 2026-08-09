"""Scrape PAGASA's dam water level table and append to data/dam_levels.csv.

The page (https://www.pagasa.dost.gov.ph/flood) shows only today and yesterday,
so this must run on a cron or the history is lost. Idempotent: re-running only
ever adds observations it hasn't seen.

Table layout, as of 2026-08: 4 rows per dam = 2 observations, each split over a
time row ("08:00 AM") and a date row ("Aug-07") with the values duplicated.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from dams import canonical  # noqa: E402

URL = "https://www.pagasa.dost.gov.ph/flood"
OUT = Path(__file__).parent / "dam_levels.csv"
UA = "Mozilla/5.0 (compatible; Pulso/0.1; +https://github.com/Zeref538/pulso)"

# Position-indexed: the table's two-row header flattens inconsistently, but the
# column order has been stable. Verified against the 2026-08-07 fixture.
COLUMNS = [
    "dam",
    "_when",
    "rwl_m",
    "_dev_hr",
    "dev_24h_m",
    "nhwl_m",
    "dev_nhwl_m",
    "rule_curve_m",
    "dev_rule_curve_m",
    "gates",
    "gate_opening_m",
    "inflow_cms",
    "outflow_cms",
]

KEY = ["dam", "obs_datetime"]


def _num(x):
    """'-' and blanks are PAGASA's missing marker."""
    if isinstance(x, str):
        x = x.strip().replace(",", "")
        if x in {"", "-", "--", "N/A", "n/a"}:
            return pd.NA
    return pd.to_numeric(x, errors="coerce")


def _resolve_year(month_day: str, scraped_at: datetime) -> datetime | None:
    """'Aug-07' has no year. Attach the scrape year, rolling back at New Year."""
    try:
        # Year supplied explicitly: strptime's yearless default is deprecated
        # and mishandles 29 Feb.
        dt = datetime.strptime(f"{month_day.strip()}-{scraped_at.year}", "%b-%d-%Y")
    except ValueError:
        return None
    # A date more than a day ahead of the scrape must belong to the previous year.
    if dt > scraped_at + timedelta(days=1):
        dt = dt.replace(year=scraped_at.year - 1)
    return dt


def parse(html: str, scraped_at: datetime) -> pd.DataFrame:
    """Return one row per (dam, observation datetime)."""
    tables = pd.read_html(io.StringIO(html))
    for t in tables:
        if t.shape[1] == len(COLUMNS) and t.astype(str).apply(
            lambda c: c.str.contains("Angat", case=False, na=False)
        ).any().any():
            raw = t
            break
    else:
        raise ValueError("dam table not found — PAGASA layout changed")

    raw = raw.copy()
    raw.columns = COLUMNS
    raw = raw[raw["dam"].astype(str).str.strip().str.lower() != "dam name"]

    value_cols = [c for c in COLUMNS if c != "dam" and not c.startswith("_")]

    records = []
    # Rows alternate time/date; the date row carries the same measurements.
    for _, grp in raw.groupby("dam", sort=False):
        rows = [grp.iloc[i] for i in range(len(grp))]
        for time_row, date_row in zip(rows[::2], rows[1::2]):
            day = _resolve_year(str(date_row["_when"]), scraped_at)
            if day is None:
                continue
            clock = pd.to_datetime(
                str(time_row["_when"]).strip().upper(),
                format="%I:%M %p",
                errors="coerce",
            )
            obs = day if pd.isna(clock) else day.replace(
                hour=clock.hour, minute=clock.minute
            )
            rec = {
                "dam": canonical(time_row["dam"]),
                "obs_datetime": obs.isoformat(timespec="minutes"),
            }
            rec.update({col: _num(time_row[col]) for col in value_cols})
            records.append(rec)

    df = pd.DataFrame.from_records(records)

    # PAGASA writes 0.00 for dams that have no NHWL or rule curve defined
    # (Caliraya, and the rule curve for Ipo / La Mesa / Caliraya). A real
    # reference elevation is never zero, so treat it as missing and blank the
    # deviations computed against it — otherwise every risk rule reads a
    # 286 m reservoir as 286 m above its limit.
    for ref, dev in (("nhwl_m", "dev_nhwl_m"), ("rule_curve_m", "dev_rule_curve_m")):
        missing = df[ref].fillna(0).eq(0)
        df.loc[missing, [ref, dev]] = pd.NA

    df["scraped_at"] = scraped_at.isoformat(timespec="seconds")
    df["source"] = "live"
    return df.sort_values(KEY).reset_index(drop=True)


def append(df: pd.DataFrame, out: Path = OUT) -> int:
    """Merge into the CSV, keeping the first-seen version of each observation."""
    if out.exists():
        old = pd.read_csv(out)
        combined = pd.concat([old, df], ignore_index=True)
    else:
        old, combined = None, df
    combined = combined.drop_duplicates(subset=KEY, keep="first").sort_values(KEY)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    return len(combined) - (0 if old is None else len(old))


def main() -> int:
    resp = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
    resp.raise_for_status()
    scraped_at = datetime.now()
    df = parse(resp.text, scraped_at)
    if df.empty:
        print("no observations parsed", file=sys.stderr)
        return 1
    added = append(df)
    print(f"parsed {len(df)} observations across {df['dam'].nunique()} dams; "
          f"{added} new rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
