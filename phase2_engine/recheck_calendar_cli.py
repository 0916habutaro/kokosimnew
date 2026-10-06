from __future__ import annotations

import argparse
import json
from datetime import date

from .recheck_calendar import (
    build_due_queue,
    load_recheck_calendar,
    summarize_due_queue,
    write_due_queue_csv,
)


def main():
    p = argparse.ArgumentParser(
        description="Stage 12O autumn checkpoint due-queue generator"
    )
    p.add_argument("--calendar", required=True, help="Stage 12N autumn recheck calendar CSV")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--output", help="Optional due-queue CSV path")
    args = p.parse_args()

    as_of = date.fromisoformat(args.as_of)
    calendar = load_recheck_calendar(args.calendar)
    due = build_due_queue(calendar, as_of)

    if args.output:
        write_due_queue_csv(due, args.output)

    print(
        json.dumps(
            summarize_due_queue(due, calendar, as_of),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
