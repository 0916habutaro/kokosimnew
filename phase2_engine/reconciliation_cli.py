from __future__ import annotations

import argparse
import json
from datetime import date

from .reconciliation import (
    build_reconciliation_status,
    load_reconciliation_queue,
    summarize_reconciliation_status,
    write_reconciliation_status_csv,
)


def main():
    p = argparse.ArgumentParser(
        description="Stage 12I autumn schedule reconciliation status generator"
    )
    p.add_argument("--queue", required=True, help="Stage 12I reconciliation queue CSV")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--output", help="Optional output CSV path")
    args = p.parse_args()

    as_of = date.fromisoformat(args.as_of)
    queue = load_reconciliation_queue(args.queue)
    statuses = build_reconciliation_status(queue, as_of)

    if args.output:
        write_reconciliation_status_csv(statuses, args.output)

    payload = summarize_reconciliation_status(statuses)
    payload["as_of"] = args.as_of
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
