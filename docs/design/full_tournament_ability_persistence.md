# Full Tournament Ability Integration / Game Data Persistence

作成日: 2026-10-07

## 目的

Stage 13C-3ではMAIN本戦だけを能力ベースMatchSimulatorへ接続した。

Stage 13C-4では同じMatchResolution契約をpre-MAINへ展開し、SeasonOrchestratorから試合モデルを選択可能にする。さらに、生成したMatchSimulationResult / GameStats / MatchEventをSQLiteへ永続化する。

## 層の責務

### Phase 2

担当:

- 大会参加校
- seed / draw
- qualifier / league / repechage
- stage transition
- bracket progression
- SeasonOrchestrator
- ResultView / browse repository

Phase 2はPlayerAbilityやMatchSimulatorの内部アルゴリズムを知らない。

### Stage 13 game_core

担当:

- roster
- PlayerAbility
- TeamStrength
- MatchSimulator
- score / winner
- MatchEvent
- GameStats

接続はPhase 2の汎用 `MatchResolution` を介する。

## pre-MAIN resolver

Stage 13C-4で以下のブラケットprimitiveへoptional `match_resolver` を追加した。

- `run_single_elimination_ranking`
- `run_single_round_gate`
- `run_block_winner_forest`
- `run_round_robin`
- `run_head_to_head`

各primitiveはresolver未指定時、従来の `WinnerResolver(team1, team2, namespace) -> school_id` を維持する。

resolver指定時は

- match_id
- competition_id
- reference_year
- generation_seed
- team1
- team2

を渡し、`MatchResolution` を受ける。

## validation

pre-MAINでもMAINと同じく以下を検証する。

- winnerは参加2校のどちらか
- loserはwinnerの反対側
- scoreは両方存在または両方なし
- scoreは非負整数
- tie禁止
- score winnerとwinner_idが一致

能力結果はMatch.metadataへ

- score_source
- team1_score
- team2_score
- winner_source

を保存する。

完全なdetailはCompetitionRun.match_simulation_resultsへ保存する。

## TournamentEngine

constructor:

```python
TournamentEngine(
    repo,
    match_resolver=resolver,
)
```

`match_resolver` はpre-MAINとMAINの両方に適用する。

Stage 13C-3互換の

`main_match_resolver=`

も残す。

main_match_resolverだけを指定した場合はMAINだけ能力モデル、pre-MAINはlegacy。

両方へ別resolverを同時指定することは禁止する。

## SeasonOrchestrator

constructor:

```python
SeasonOrchestrator(
    repo,
    data_dir,
    match_resolver=resolver,
)
```

SeasonOrchestrator自体はgame_coreをimportしない。

受け取ったgeneric resolverをTournamentEngineへ注入するだけにする。

## CLI composition root

`phase2_engine.season_cli` で

- `--match-model legacy`
- `--match-model ability`

を選択可能。

ability選択時のみcomposition rootで `AbilityMatchResolver` を生成する。

設定ディレクトリ:

- `--ability-config-dir`
- `--match-config-dir`

defaultはlegacyとし、既存Stage 12構造監査の結果を変えない。

## AbilityMatchResolver

Stage 13C-3の `AbilityMainMatchResolver` を一般化。

新正本名:

`AbilityMatchResolver`

旧名はaliasとして残し、既存呼び出しを破壊しない。

同一

- reference_year
- generation_seed
- school_id

のTeamMatchInputをcacheする。

## SQLite schema v2

Stage 12Rのbrowse DBをschema version 2へ拡張する。

既存:

- browse_seasons
- matches_by_date
- competition_results
- school_records

追加:

### ability_matches

1試合1row。

- score
- winner / loser
- inning
- score_source
- match/event/stats config provenance

primary key:

`year + competition_id + match_id`

### batter_game_stats

1試合・1打者1row。

primary key:

`year + competition_id + match_id + player_id`

### pitcher_game_stats

1試合・1投手1row。

### team_game_stats

1試合・1学校1row。

### match_events

1event 1row。

primary key:

`year + competition_id + match_id + event_no`

metadataはJSON文字列として保存する。

## replace semantics

`replace_season_views()` が同年度のbrowse layerを置換した後、

`replace_season_game_data()`

で同年度のability game dataを全置換する。

同じSeasonExecutionを再保存してもrowが重複しない。

browse_seasonsを親としてON DELETE CASCADEを利用するため、season view置換時に旧game dataも消える。

## read API

Stage 13C-4では最低限以下を用意する。

- `ability_matches(year, competition_id=...)`
- `batter_games(year, player_id)`
- `pitcher_games(year, player_id)`
- `events_for_match(year, competition_id, match_id)`

Stage 13Dではこれらを基礎に大会・シーズン・通算集約read modelを追加する。

## 非目標

Stage 13C-4ではまだ以下を実装しない。

- AVG / OPS / ERAランキング
- career aggregate table
- player masterのSQLite正本化
- GUIの正式作り込み

これらはStage 13D以降。
