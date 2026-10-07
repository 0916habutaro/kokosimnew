# ADR-013: 個人成績の率指標はGameStats countからread時に導出する

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 13C-4で試合単位の打者・投手GameStatsがSQLiteへ保存された。

Stage 13DではAVG・OPS・ERA・WHIP等を表示する必要がある。

これらの率指標をSQLiteへ保存すると、試合結果の修正・集計範囲変更・式変更のたびに再計算して同期する必要があり、countとrateの二重正本になる。

## Decision

SQLiteへ保存する正本はGameStatsの整数countだけとする。

PlayerStatsReadModelが

- year
- competition
- school
- player

のfilterでcountを集計し、率指標をread時に導出する。

ランキング規定値とsort方向のみversion付きJSON configで管理する。

## Consequences

### 利点

- 大会別／シーズン別で同じ正本から再集計できる
- rate式変更時にmigration不要
- countとrateの不整合を防止できる
- SQLite schemaを不必要に増やさない

### 注意

- leaderboard取得時に集計計算が発生する
- 将来データ量が大きくなり性能が問題になった場合、cache/materialized read modelを追加できる
- その場合もGameStats countを正本とする
