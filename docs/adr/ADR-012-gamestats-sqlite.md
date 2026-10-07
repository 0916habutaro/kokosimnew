# ADR-012: GameStatsとMatchEventをBrowseRepository SQLiteへ同居させる

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 12Rで結果閲覧用SQLite BrowseRepositoryが存在する。

Stage 13C-3でGameStats / MatchEventはCSV保存できるようになったが、Stage 13Dで個人成績・ランキングを高速に読むにはSQLite上の正規化データが必要。

別DBを新設すると、試合結果閲覧DBと個人成績DBのyear/version管理が分離する。

## Decision

BrowseRepositoryをschema version 2へ更新し、同じSQLite DBへ以下を追加する。

- ability_matches
- batter_game_stats
- pitcher_game_stats
- team_game_stats
- match_events

year / competition_id / match_idを共通キーとする。

既存browse tablesは維持する。

## Consequences

- GUI/read modelは1DBから試合結果と個人成績を読める
- Stage 13Dのaggregate queryを追加しやすい
- year replace時に詳細GameStatsも同時更新できる
- schema migration管理が必要になる

現段階ではschemaをCREATE IF NOT EXISTSで追加し、PRAGMA user_version=2とする。
