# Stage 13D-2 Player Master / Roster Stats / GUI Contract

作成日: 2026-10-07

## 目的

Stage 13D-1で作成した個人成績read modelへ、選手表示名・学年・守備位置等のplayer masterを結合し、

- 学校ロスター＋個人成績
- 選手詳細
- 大会別打撃／投手ランキング
- 選手検索

をGUIから読める契約へ拡張する。

## 重要な前提修正

Stage 13C-4時点ではAbilityMatchResolverがTournamentEngineから渡された
`generation_seed`
を

- MatchSimulatorの試合乱数
- PlayerRosterGenerator
- PlayerAbilityGenerator
- TeamStrengthGenerator

の両方へ使っていた。

SeasonOrchestratorは大会ごとに異なるseedを派生するため、このままでは同じ学校の選手identityが春・夏・秋で変わり得る。

Stage 13D-2では以下を分離する。

### match generation seed

用途:

- plate appearance RNG
- event RNG
- 試合結果再現

大会・matchごとに変化してよい。

### team generation seed

用途:

- player_id
- roster
- PlayerAbilitySnapshot
- TeamStrengthSnapshot

同一年のシーズン中は固定する。

SeasonOrchestratorはAbilityMatchResolver.begin_season(year, season_seed)を呼び、
シーズン共通team generation seedを設定する。

## MatchSimulationInput

追加:

`team_generation_seed: int | None`

未指定時:

`generation_seed`

を使い、Stage 13Cまでのcallerとの互換性を維持する。

指定時:

TeamStrength / PlayerAbilitySnapshotのgeneration_seedはteam_generation_seedと一致する必要がある。

MatchSimulationResult.generation_seedは従来通りmatch generation seedを表す。

## AbilityMatchResolver

### begin_season

```
begin_season(reference_year, season_generation_seed)
```

を追加。

呼び出すとteam/roster cacheをclearし、その年のteam generation seedを固定する。

### cache key

```
(reference_year, team_generation_seed, school_id)
```

同じ学校は大会ごとのmatch seedが異なっても同じTeamMatchInputを共有する。

### player_master_records

生成済みSchoolRosterを重複除去し

```
player_id -> player master dict
```

として返す。

GameStatsへdisplay_name等は埋め込まない。

## SeasonExecution

追加:

`player_master_records`

SeasonOrchestrator終了時にresolverのplayer master snapshotを取り込む。

summaryへ

`player_master_count`

を追加する。

resolverがplayer master capabilityを持たない場合は空dictのまま。

## SQLite schema v3

新規table:

`player_master`

primary key:

`year + player_id`

保存項目:

- player_id
- school_id
- program_id
- display_name
- name_source
- academic_year
- entry_year
- roster_no
- primary_position
- position_group
- bats
- throws
- roster_status
- generation_seed

reference_yearはtableのyear列を使用する。

school_nameはschool_recordsからjoinし、masterへ重複保存しない。

## GameStatsとの関係

batter_game_stats / pitcher_game_statsは従来通りplayer_idだけを保持する。

aggregate queryはplayer_masterをLEFT JOINする。

masterがない旧fixture / 移行中DBでは

- player_name = player_id
- academic_year = 0
- position = empty

へfallbackする。

これによりStage 13D-1の既存read model互換性を維持する。

## PlayerStatsReadModel

BatterAggregate / PitcherAggregateへ追加:

- player_name
- academic_year
- roster_no
- primary_position
- bats
- throws

RankingRowへ追加:

- player_name
- academic_year
- primary_position

player_summary()は

- player master
- batter aggregate
- pitcher aggregate

を1payloadにまとめる。

school_roster_summary()は20人のmasterを正本にし、試合出場がないbench playerも返す。

## BrowseRepository read API

追加:

- player_record()
- school_roster()
- search_players()

## BrowseGuiModel contract

追加:

### search_players

選手名 / player_id / school / positionで検索。

### school_roster_stats

学校20人masterへ大会別またはseason個人成績を結合。

### player_detail

player master + batting + pitching。

### competition_leaderboards

1大会の

- batting leaderboard
- pitching leaderboard

を同時に返す。

Stage 13D-2では正式GUI widget自体は作り込まない。
画面はこのpure read payloadを使用する。

## 年度進行との関係

Stage 13D-2は「同一年のidentity固定」までを扱う。

翌年度に

- 卒業
- 進級
- 新入生
- 同じplayer_id継続

を行う仕組みはStage 13Fで実装する。

現状のPlayerRosterGeneratorはreference_yearをplayer_idへ含むため、年度を跨ぐidentity継続はまだ行わない。

## Stage 43E追記：年度を跨ぐ選手IDの継続基盤（2026-10-10）

上記「Stage 13Fで実装する」「年度を跨ぐidentity継続はまだ行わない」は**Stage 13D-2策定当時の記述**である。その後、Stage 43Eで年度継続の**基礎モジュール**を実装した。

- `game_core/career_rosters.py`：前年度の確定ロスターを入力として、在学選手のplayer_idを変えずに進級、3年生は卒業、新1年生は新規IDで登録。
- `phase2_engine/career_roster_archive.py`：学校年度別ロスター・選手ID別の履歴を不変スナップショットとして永続保存。学校・年度・選手IDから履歴を参照可能。
- `game_core/tournament_bridge.py`：任意の`roster_provider`指定で保存済み永続ロスターを能力試合に使用可能。既定の2026年生成経路は不変。
- 初年度の学年数5/7/8を毎年強制せず、実際に残る在学選手を優先する。2027年は8/5/7、2028年は7/8/5となる。
- **未実装**：実際のゲーム本編で2027年大会へ年度進行させる経路、セーブスロットの試合履歴と全校ロスター履歴の一体保存、選手成長・退部、正式GUIの歴代所属選手画面。

詳細とテスト範囲は[Stage 43E 日本語報告書](../research/stage43e_player_career_continuity_20261010.md)を参照。
