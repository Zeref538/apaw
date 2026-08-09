"""One-shot: recover historical dam levels from Wayback Machine snapshots.

PAGASA keeps no archive — the page shows today and yesterday only. The Internet
Archive happens to have ~90 daily snapshots of /flood since 2021, roughly 1.5
per month. That is far too sparse to train on, but it anchors the early
learning curve and gives the backtest something to chew on before the
collector has accrued its own history.

Snapshots are marked source="wayback" so they can be excluded from any
analysis that assumes a regular daily cadence.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from fetch_dams import OUT, append, parse  # noqa: E402

CDX = "http://web.archive.org/cdx/search/cdx"
SNAPSHOT = "http://web.archive.org/web/{ts}id_/https://www.pagasa.dost.gov.ph/flood"
UA = "Mozilla/5.0 (compatible; Pulso/0.1; +https://github.com/Zeref538/pulso)"


def _fetch(url: str, attempts: int = 4) -> requests.Response:
    """The archive resets a lot of connections; roughly half fail first try."""
    last = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            last = exc
            time.sleep(3 * (attempt + 1))
    raise last


def list_snapshots() -> list[str]:
    r = requests.get(CDX, params={
        "url": "www.pagasa.dost.gov.ph/flood",
        "output": "json", "fl": "timestamp", "filter": "statuscode:200",
        "collapse": "timestamp:8",  # at most one per day
    }, timeout=120)
    r.raise_for_status()
    rows = r.json()
    return [row[0] for row in rows[1:]]


def main() -> int:
    stamps = list_snapshots()

    # Re-runs only chase the snapshots that failed last time.
    done = set()
    if OUT.exists():
        prior = pd.read_csv(OUT)
        done = set(prior.loc[prior["source"] == "wayback", "scraped_at"].astype(str))
    stamps = [
        ts for ts in stamps
        if datetime.strptime(ts, "%Y%m%d%H%M%S").isoformat(timespec="seconds")
        not in done
    ]
    print(f"{len(stamps)} snapshots to fetch ({len(done)} already recovered)")
    if not stamps:
        print("nothing left to recover")
        return 0

    frames, failed = [], 0
    for i, ts in enumerate(stamps, 1):
        try:
            r = _fetch(SNAPSHOT.format(ts=ts))
            # Stamp with the snapshot's own capture time, not today's, or the
            # year-rollover logic will mis-date every historical row.
            captured = datetime.strptime(ts, "%Y%m%d%H%M%S")
            df = parse(r.text, captured)
            df["source"] = "wayback"
            df["scraped_at"] = captured.isoformat(timespec="seconds")
            frames.append(df)
        except Exception as exc:  # noqa: BLE001 - old layouts vary; skip and count
            failed += 1
            print(f"  [{i}/{len(stamps)}] {ts} skipped: {type(exc).__name__}")
            continue
        print(f"  [{i}/{len(stamps)}] {ts} -> {len(df)} rows", flush=True)
        time.sleep(1)  # be polite to the archive

    if not frames:
        print("nothing recovered", file=sys.stderr)
        return 1

    recovered = pd.concat(frames, ignore_index=True)
    # Live scrapes always win over an archived copy of the same observation.
    added = append(recovered.sort_values("scraped_at"), OUT)
    print(f"recovered {len(recovered)} observations "
          f"({recovered['obs_datetime'].min()} .. {recovered['obs_datetime'].max()}), "
          f"{failed} snapshots unparseable, {added} new rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
