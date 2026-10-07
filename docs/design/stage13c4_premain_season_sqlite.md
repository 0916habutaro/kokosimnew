# Stage 13C-4 pre-MAIN / Season / SQLite integration

作成日: 2026-10-07

## 目的

Stage 13C-3でMAIN本戦だけに接続した能力ベース試合を、pre-MAIN共通bracket・SeasonOrchestrator・SQLite永続化まで拡張する。

## 接続範囲

pre-MAINの個別大会方式を直接書き換えず、既存の共通bracket関数へ `MatchResolution` を注入可能にする。

対象:

- single elimination ranking
- single round gate
- block winner forest
- round robin
- head-to-head

これにより、これらを利用する

- SEED_EVENT
- BRANCH_QUALIFIER
- PRELIMINARY_QUALIFIER
- FIRST_TOURNAMENT
- repechage
- league / ranking
- cross playoff

などへ同じ能力resolverを展開できる。

## TournamentEngine

constructor:

```
TournamentEngine(
    repo,
    main_match_resolver=...,
    pre_main_match_resolver=...,
)
```

resolver未指定時は従来random winner resolverを維持する。

pre-MAIN詳細結果は大会実行中のresult sinkへ蓄積し、MAIN開始前に `CompetitionRun.match_simulation_results` へ取り込む。

MAIN結果も同じdictへ追加されるため、大会全体で1つのmatch_id namespaceとして扱う。

## AbilityMatchResolver

Stage 13C-3の `AbilityMainMatchResolver` を汎用 `AbilityMatchResolver` へ一般化した。

後方互換alias:

`AbilityMainMatchResolver = AbilityMatchResolver`

入力matchがMAINかpre-MAINかをresolver側では区別しない。

すべて

```
school_id
 -> roster
 -> school-aware ability
 -> TeamStrength
 -> MatchSimulator
 -> MatchResolution
```

で処理する。

同じ year / seed / school_id はTeamMatchInput cacheを共有する。

## SeasonOrchestrator

constructor:

```
SeasonOrchestrator(
    repo,
    data_dir,
    match_resolver=resolver,
)
```

同一resolverを

- TournamentEngine.main_match_resolver
- TournamentEngine.pre_main_match_resolver

へ配線する。

resolver未指定時の既存Stage 12 structural season動作は変更しない。

SeasonExecution.summary()には以下を追加する。

- ability_match_count
- ability_competition_count

フルシーズンを能力モデルで実行した際の監査指標として使う。

## SQLite schema v2

既存BrowseRepositoryをschema version 2へ更新する。

既存テーブル:

- browse_seasons
- matches_by_date
- competition_results
- school_records

は維持する。

追加:

### ability_matches

1試合1row。

保持:

- competition / match id
- generation seed
- team ids
- score
- winner / loser
- inning / ending half
- score_source
- match / event / stats config provenance

### batter_game_stats

primary key:

`year + competition_id + match_id + player_id`

GameStats整数countを保存する。

### pitcher_game_stats

投手GameStatsを保存。

### team_game_stats

学校単位の1試合R/H/Eを保存。

### match_events

1 event 1row。

metadataは `metadata_json` としてcanonicalに保存する。

## SQLite書き込み

`save_season_browse_repository()` は

1. browse viewsをreplace
2. SeasonExecution内の全 `match_simulation_results` をreplace

の順で同じyearへ保存する。

GameStats側はyear単位replaceであり、再実行時に古い能力試合rowを残さない。

## Read API

Stage 13Dへ向けて以下を追加する。

- ability_match(year, competition_id, match_id)
- player_batter_game_stats(year, player_id)
- player_pitcher_game_stats(year, player_id)
- events_for_match(year, competition_id, match_id)

Stage 13Dではこれらの生GameStatsを元に大会・シーズン・通算read modelを構築する。

## 実pre-MAIN検証

岐阜秋 `CMP000110` を使用。

構造:

```
SEED_EVENT
 -> FIRST_TOURNAMENT
 -> MAIN
```

Stage 12C既存fixtureと同じ58校構成でAbilityMatchResolverをMAIN/pre-MAIN双方へ注入。

全非bye Matchのmatch_id集合と `CompetitionRun.match_simulation_results` のkey集合が一致することを検証する。

また全played matchのscore_sourceが `ability_model_v1` であることを確認する。

## 常設CI方針

フル2026 seasonを毎PRで能力試合化すると計算量が大きいため、Stage 13C-4では以下を常設回帰とする。

- 4種類の共通bracket resolver contract
- block forest伝播
- real Gifu pre-MAIN + MAIN
- SeasonOrchestrator resolver wiring
- 4校ability tournament -> SQLite round-trip
- legacy tests全件

フルシーズン能力監査は必要な節目で別auditとして実行する。
