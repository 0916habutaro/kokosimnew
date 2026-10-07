# Stage 13D-1 個人成績read model・ランキング 実装報告

作成日: 2026-10-07

## 目的

Stage 13C-4のSQLite v2に保存されたGameStatsから、大会別／シーズン別の個人成績とランキングを作る。

## 実装

### BrowseRepository

追加:

- aggregate_batter_counts()
- aggregate_pitcher_counts()
- team_game_counts()

filter:

- competition_id
- school_id
- player_id

### PlayerStatsReadModel

新規:

`phase2_engine/player_stats_read_model.py`

dataclass:

- BatterAggregate
- PitcherAggregate
- RankingRow

API:

- batter_aggregates()
- pitcher_aggregates()
- batter_rankings()
- pitcher_rankings()
- player_summary()

### Batter

導出:

- total bases
- AVG
- OBP
- SLG
- OPS
- ISO

### Pitcher

導出:

- innings display
- ERA
- WHIP
- K/9
- BB/9
- K/BB
- K-BB%

投球回はouts_recordedから表示する。

### Ranking config

`config/stats/player_rankings_v1.json`

status:

`design_default_not_tuned`

規定PA / outsはゲーム内ranking用の初期値。

公式高校野球規定とは扱わない。

### GUI model

`BrowseGuiModel` に

- player_stats_summary
- batting_leaderboard
- pitching_leaderboard

を追加。

正式GUIの画面構築は後続工程。

## Fixture validation

固定SQLite fixtureで以下を数式レベルで検証する。

### batter B1

season:

- AB 8
- H 4
- BB 1
- TB 11

期待:

- AVG .500
- OBP .556
- SLG 1.375
- OPS 1.931
- ISO .875

### pitcher P1

season:

- outs 15 = 5 innings
- ER 3
- H 5
- BB 2
- K 7
- BF 22

期待:

- ERA 5.400
- WHIP 1.400
- K/9 12.600
- BB/9 3.600
- K/BB 3.500
- K-BB% 22.727

### qualification

- rate rankingは規定到達者のみ
- count rankingは未到達者も含む
- competition filter時はteam_gamesも対象大会だけで再計算

### tie

同値metricはcompetition ranking方式で同順位。

## 次工程

Stage 13D-2候補:

- 選手master / player name persistence
- 個人成績画面
- 学校ロスター成績一覧
- 大会ランキング画面
- batting / pitching leaderboard GUI navigation


## GitHub Actions

実装コード・専用fixtureを含むfull suite:

- Python 3.12
- 451 tests
- OK

Stage 13D-1専用テスト: 12件。
