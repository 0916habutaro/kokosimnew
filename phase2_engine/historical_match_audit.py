"""Read-only Stage 43 audit of historical match retention (Option A).

This does not assert that a missing inning-score table or missing GameStats
can be reconstructed from scores, dates, RNG seeds, or batting events.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


REQUIRED_TABLES = ("browse_seasons", "matches_by_date")
OPTIONAL_STATS_TABLES = (
    "ability_matches", "team_game_stats",
    "batter_game_stats", "pitcher_game_stats",
)
LINE_SCORE_COLUMNS = frozenset({
    "year", "competition_id", "match_id",
    "inning", "half", "runs", "was_played",
})


def _one(conn: sqlite3.Connection, sql: str, year: int) -> int:
    value = conn.execute(sql, (year,)).fetchone()[0]
    return int(value or 0)


def audit_historical_matches(
    db_path: str | Path,
    *,
    year: int | None = None,
) -> dict:
    """Inspect stored facts without modifying SQLite or assuming event retention.

    A-1: score-bearing non-bye match rows.
    A-2: independently stored, score-reconciled inning data, when available.
    A-3/4: presence of team/batter/pitcher game stats for the *same match*.
    These are structural presence checks, not a full sporting validity audit.
    """
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite DB not found: {path}")
    if year is not None and (not isinstance(year, int) or year < 1):
        raise ValueError("year must be a positive integer")

    # URI mode=ro is intentional: BrowseRepository's normal connection
    # initializes its schema and may issue DDL even for GUI reads.
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = set(REQUIRED_TABLES) - tables
        if missing:
            raise ValueError(f"browse DB missing tables: {sorted(missing)}")

        if year is None:
            years = [
                int(row[0]) for row in conn.execute(
                    "SELECT year FROM browse_seasons ORDER BY year"
                )
            ]
        else:
            if conn.execute(
                "SELECT 1 FROM browse_seasons WHERE year = ?", (year,)
            ).fetchone() is None:
                raise ValueError(f"year not found in browse_seasons: {year}")
            years = [year]

        present_stats = all(t in tables for t in OPTIONAL_STATS_TABLES)
        inning_schema = "absent"
        if "match_inning_scores" in tables:
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(match_inning_scores)")
            }
            inning_schema = (
                "recognized" if LINE_SCORE_COLUMNS <= cols else "unsupported"
            )

        outputs = []
        for y in years:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_bye = 1 THEN 1 ELSE 0 END) AS byes,
                    SUM(CASE WHEN is_bye = 0 THEN 1 ELSE 0 END) AS played_rows,
                    SUM(CASE WHEN is_bye = 0
                        AND team1_score IS NOT NULL
                        AND team2_score IS NOT NULL
                        THEN 1 ELSE 0 END) AS score_rows
                FROM matches_by_date WHERE year = ?
                """,
                (y,),
            ).fetchone()
            total, byes, played, scored = (int(v or 0) for v in row)

            stats_matches = 0
            score_conflicts = 0
            if present_stats:
                stats_matches = _one(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM matches_by_date AS m
                    WHERE m.year = ? AND m.is_bye = 0
                      AND m.team1_score IS NOT NULL
                      AND m.team2_score IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM ability_matches AS a
                        WHERE a.year=m.year
                          AND a.competition_id=m.competition_id
                          AND a.match_id=m.match_id
                      )
                      AND (
                        SELECT COUNT(*) FROM team_game_stats AS t
                        WHERE t.year=m.year
                          AND t.competition_id=m.competition_id
                          AND t.match_id=m.match_id
                      ) = 2
                      AND EXISTS (
                        SELECT 1 FROM batter_game_stats AS b
                        WHERE b.year=m.year
                          AND b.competition_id=m.competition_id
                          AND b.match_id=m.match_id
                      )
                      AND EXISTS (
                        SELECT 1 FROM pitcher_game_stats AS p
                        WHERE p.year=m.year
                          AND p.competition_id=m.competition_id
                          AND p.match_id=m.match_id
                      )
                    """,
                    y,
                )
                score_conflicts = _one(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM matches_by_date AS m
                    JOIN ability_matches AS a
                      ON a.year=m.year AND a.competition_id=m.competition_id
                     AND a.match_id=m.match_id
                    WHERE m.year=? AND m.is_bye=0
                      AND m.team1_score IS NOT NULL
                      AND m.team2_score IS NOT NULL
                      AND (m.team1_score<>a.team1_score
                        OR m.team2_score<>a.team2_score)
                    """,
                    y,
                )

            inning_matches = 0
            if inning_schema == "recognized":
                inning_matches = _one(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM matches_by_date AS m
                    WHERE m.year = ? AND m.is_bye=0
                      AND m.team1_score IS NOT NULL
                      AND m.team2_score IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM match_inning_scores AS i
                        WHERE i.year=m.year AND i.competition_id=m.competition_id
                          AND i.match_id=m.match_id AND i.half='top'
                          AND i.was_played=1
                      )
                      AND (
                        SELECT COALESCE(SUM(i.runs), 0)
                        FROM match_inning_scores AS i
                        WHERE i.year=m.year AND i.competition_id=m.competition_id
                          AND i.match_id=m.match_id AND i.half='top'
                          AND i.was_played=1
                      )=m.team1_score
                      AND (
                        SELECT COALESCE(SUM(i.runs), 0)
                        FROM match_inning_scores AS i
                        WHERE i.year=m.year AND i.competition_id=m.competition_id
                          AND i.match_id=m.match_id AND i.half='bottom'
                          AND i.was_played=1
                      )=m.team2_score
                    """,
                    y,
                )

            # A-2 and GameStats coverage refer to potentially different
            # matches. Never infer FULL_A by taking min(counts).
            outputs.append({
                "year": y,
                "total_match_rows": total,
                "bye_rows": byes,
                "non_bye_rows": played,
                "scored_match_rows": scored,
                "unscored_non_bye_rows": played - scored,
                "match_rows_with_game_stats": stats_matches,
                "match_rows_with_reconciled_inning_totals": inning_matches,
                "score_conflicts_between_sources": score_conflicts,
                "full_a_claimed": False,
                "notes": "coverage counts do not prove the same matches have both data sets",
            })

        return {
            "database": str(path),
            "audit_policy": "historical_match_retention_option_a",
            "readonly": True,
            "inning_score_schema": inning_schema,
            "stats_tables_present": present_stats,
            "years": outputs,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 43: SQLite過去試合記録A方式・読取専用充足監査"
    )
    parser.add_argument("--db", required=True, help="既存browse SQLite DB")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--output", help="任意のJSON出力先（DBは変更しない）")
    args = parser.parse_args()
    payload = audit_historical_matches(args.db, year=args.year)
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
