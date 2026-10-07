# Stage 13D-1 Player Stats Read Model

作成日: 2026-10-07

## 目的

Stage 13C-4でSQLiteへ保存した試合単位の整数GameStatsを正本として、選手単位の大会別・シーズン別個人成績とランキングを読み出す。

Stage 13D-1では集計値を新しいSQLite tableへ保存しない。

```
batter_game_stats / pitcher_game_stats
    -> SQL count aggregate
    -> PlayerStatsReadModel
    -> derived rate stats
    -> player summary / leaderboard
```

とする。

## 正本

### batter

SQLite `batter_game_stats` の整数count:

- PA
- AB
- R
- H
- 1B
- 2B
- 3B
- HR
- RBI
- BB
- SO
- HBP
- SF
- SH
- SB
- CS

### pitcher

SQLite `pitcher_game_stats` の整数count:

- outs_recorded
- batters_faced
- runs_allowed
- earned_runs
- hits_allowed
- home_runs_allowed
- walks
- strikeouts
- hit_batters

## SQL aggregate

`BrowseRepository` に以下を追加する。

- aggregate_batter_counts()
- aggregate_pitcher_counts()
- team_game_counts()

filter:

- year
- competition_id
- school_id
- player_id

yearは必須。

competition / school / playerはoptional。

学校名は `school_records` とjoinして取得する。

## Batter derived stats

### Total Bases

```
TB = 1B + 2*2B + 3*3B + 4*HR
```

### AVG

```
AVG = H / AB
```

AB=0はNone。

### OBP

```
OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
```

Stage 13C v1 contractにcatcher interference等は存在しないため、この式を使う。

### SLG

```
SLG = TB / AB
```

### OPS

```
OPS = OBP + SLG
```

### ISO

```
ISO = SLG - AVG
```

## Pitcher derived stats

投球回の正本は常に `outs_recorded`。

### innings display

- 18 outs -> `6`
- 19 outs -> `6 1/3`
- 20 outs -> `6 2/3`

`6.1` / `6.2` を数値として扱わない。

### ERA

```
ERA = ER * 27 / outs_recorded
```

### WHIP

```
WHIP = (H + BB) * 3 / outs_recorded
```

### K/9

```
K/9 = SO * 27 / outs_recorded
```

### BB/9

```
BB/9 = BB * 27 / outs_recorded
```

### K/BB

```
K/BB = SO / BB
```

BB=0はNoneとする。

無限大値をランキングへ入れない。

### K-BB%

```
K-BB% = (SO - BB) / BF * 100
```

BF=0はNone。

## Ranking qualification

設定:

`config/stats/player_rankings_v1.json`

status:

`design_default_not_tuned`

### batter

初期値:

```
minimum_team_games = 1
plate_appearances_per_team_game = 2.0
```

必要PA:

```
ceil(team_games * 2.0)
```

### pitcher

初期値:

```
minimum_team_games = 1
outs_recorded_per_team_game = 3.0
```

必要outs:

```
ceil(team_games * 3.0)
```

これらはゲーム内ランキング表示の初期設計値。

高校野球の公式表彰・記録規定を意味しない。

後でゲームバランスを調整する場合はconfig revisionを上げる。

## Rate vs count ranking

rate metric:

### batter

- batting_average
- on_base_percentage
- slugging_percentage
- ops

### pitcher

- earned_run_average
- whip
- strikeouts_per_9
- walks_per_9
- strikeout_walk_ratio
- k_minus_bb_pct

rate metricはqualified playerのみ。

count metricは規定到達を要求しない。

例:

- hits
- home_runs
- RBI
- strikeouts

## Sort direction

configでmetricごとに

- asc
- desc

を定義する。

ERA / WHIP / BB/9はasc。

打撃率・OPS・HR・K等はdesc。

## Tie ranking

同じ表示値は同順位。

例:

```
1, 1, 3
```

competition ranking方式。

同値内の安定順序はplayer_id。

## Player summary

`player_summary()` は同じplayer_idについて

- batter aggregate
- pitcher aggregate

を1objectへまとめる。

野手のみならpitcher=None。

投手でも打席が存在すれば両方を持てる。

## GUI境界

`BrowseGuiModel` に

- player_stats_summary()
- batting_leaderboard()
- pitching_leaderboard()

を追加する。

Stage 13D-1では正式GUI画面自体はまだ作り込まない。

Tkinter / 将来正式GUIはこのpure read adapterを使う。

## 選手名

Stage 13D-1のSQLite GameStats正本はplayer_id / school_idを保持する。

選手名・プロフィールの永続化は別のplayer master persistence工程で扱う。

個人成績countへ名前を重複保存しない。
