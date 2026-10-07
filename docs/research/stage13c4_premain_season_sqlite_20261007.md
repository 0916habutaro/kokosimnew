# Stage 13C-4 実装・検証報告

作成日: 2026-10-07

## 実装

### pre-MAIN

`phase2_engine/brackets.py`

以下をMatchResolution対応。

- run_single_elimination_ranking
- run_single_round_gate
- run_block_winner_forest
- run_round_robin
- run_head_to_head

resolverが返すscore / winner / loserを検証し、Match.metadataへscoreを保持する。

full detailはresolved_match_sinkへ保存する。

### TournamentEngine

`pre_main_match_resolver` を追加。

pre-MAINで生成された詳細結果を `CompetitionRun.match_simulation_results` へ統合し、その後MAINの能力結果も同じdictへ追加する。

### Ability resolver

`AbilityMainMatchResolver` を `AbilityMatchResolver` へ一般化。

旧名aliasを残した。

### Season

SeasonOrchestratorにoptional `match_resolver` を追加。

同resolverをMAIN/pre-MAINへ配線する。

Season summaryへ

- ability_match_count
- ability_competition_count

を追加。

### SQLite

BrowseRepository schema version 2。

追加テーブル:

- ability_matches
- batter_game_stats
- pitcher_game_stats
- team_game_stats
- match_events

追加read API:

- ability_match
- player_batter_game_stats
- player_pitcher_game_stats
- events_for_match

## 実大会検証

岐阜秋 `CMP000110`。

58校fixtureで

```
SEED_EVENT
→ FIRST_TOURNAMENT
→ MAIN
```

をAbilityMatchResolverで完走。

確認:

- stage sequence一致
- 全非bye matchがability_model_v1
- played match_id集合 = match_simulation_results key集合
- MAIN championがmain entrant内
- 58校TeamMatchInput cache

## SQLite round-trip

4校direct MAIN大会をability modelで実行。

3試合をSQLite v2へ保存。

確認:

- ability_matches 3
- batter game stats 54
- team game stats 6
- pitcher rows > 0
- events > 0
- winner / score round-trip一致
- player batter GameStats query成功
- match event query件数一致

## GitHub Actions

実pre-MAIN追加後:

- Python 3.12
- `Ran 439 tests in 18.143s`
- **OK**

Stage 13C-4専用テスト: 9件。

## 判断

Stage 13C-4を採用。

MAIN/pre-MAINの能力試合境界が統一され、SeasonOrchestratorからopt-in可能になった。

またGameStats / MatchEventがSQLiteへ永続化されたため、次工程Stage 13Dの個人成績read modelに進める。

## 次工程

Stage 13D-1:

- batter season aggregate
- pitcher season aggregate
- AVG / OBP / SLG / OPS
- ERA / WHIP / K/BB
- school / competition / season filter
- ranking read model
- SQLite queryとGUI表示契約
