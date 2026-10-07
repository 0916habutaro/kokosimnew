# Game Event / Stats Contract v1

作成日: 2026-10-07

## 目的

試合結果の得点だけでなく、後から

- 個人成績
- 学校別成績
- 大会ランキング
- 選手詳細画面
- 通算成績

を再構成できるよう、試合イベントとゲーム単位成績の最小契約を固定する。

## 原則

```
PlayerAbility
  -> MatchEvent
  -> GameStats
  -> Season / Career aggregate
  -> read model
```

打率・OPS・防御率などの率指標を試合イベントへ直接保存しない。

## MatchEvent

Stage 13C-1 v1は1打席=1eventを基本とする。

主なフィールド:

- event_no
- plate_appearance_no
- inning
- half
- offense_school_id
- defense_school_id
- batter_id
- pitcher_id
- event_type
- runs_scored
- outs_on_play
- rbi
- metadata

event_no / plate_appearance_noは1から連番。

将来、盗塁・暴投・牽制・投手交代などの非打席イベントを追加する場合はevent catalog revisionで拡張する。

## Event catalog v1

最小イベント:

- strikeout
- walk
- hit_by_pitch
- single
- double
- triple
- home_run
- field_out
- fielder_choice
- reached_on_error
- sacrifice_bunt
- sacrifice_fly

各event typeに

- category
- is_plate_appearance
- counts_as_at_bat
- hit_value
- default_outs_on_play

を持たせる。

## BatterGameStats

保存項目:

- plate_appearances
- at_bats
- runs
- hits
- doubles
- triples
- home_runs
- rbi
- walks
- strikeouts
- hit_by_pitch
- sacrifice_flies
- sacrifice_bunts
- stolen_bases
- caught_stealing

基本整合式:

```
PA = AB + BB + HBP + SF + SH
1B = H - 2B - 3B - HR
```

Stage 13C-1ではcatcher interference等をcatalogに含めないため、このPA式をv1契約とする。

## PitcherGameStats

保存項目:

- outs_recorded
- batters_faced
- runs_allowed
- earned_runs
- hits_allowed
- home_runs_allowed
- walks
- strikeouts
- hit_batters

投球回はfloatや「6.2」のような野球表記で保存せず、`outs_recorded` を正本とする。

表示時に

- 18 outs = 6回
- 20 outs = 6回2/3

のようにread modelで変換する。

## TeamGameStats

- runs
- hits
- errors

## rate stats

保存しない:

- batting average
- on-base percentage
- slugging
- OPS
- ERA
- WHIP
- K/BB

これらは整数countからread modelで計算する。

## 試合全体のreconciliation

完了した `MatchSimulationResult` では以下を一致させる。

### 得点

- team score = TeamGameStats.runs
- team score = offense eventsのruns_scored合計
- team runs = batter runs合計
- team runs = opponent pitchersのruns_allowed合計

### 安打

- team hits = batter hits合計
- team hits = opponent pitchersのhits_allowed合計

### 打席

- team batter PA合計 = opponent pitchersのbatters_faced合計

### ID

- event batterは攻撃側ロスターに存在
- event pitcherは守備側ロスターに存在しprimary_position=P
- 個人成績rowも試合入力ロスター内のplayer_idだけを許可

## earned run

Stage 13C-1ではearned_runsフィールドと `earned_runs <= runs_allowed` の整合だけを固定する。

失策・自責点判定の詳細アルゴリズムはStage 13C-2以降。

## aggregation

GameStatsは1試合単位の不変記録。

Stage 13Dで

```
GameStats
 -> TournamentStats
 -> SeasonStats
 -> CareerStats
```

へ集約する。

集約値から元のGameStatsを逆算して更新する設計にはしない。
