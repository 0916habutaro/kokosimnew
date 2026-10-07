# Stage 13C-3 TournamentEngine能力モデル正式接続 実装報告

作成日: 2026-10-07

## 実装目的

Stage 13C-2まではMatchSimulator単体で完全試合を生成できたが、大会ブラケットは従来のrandom winner resolverで進行していた。

Stage 13C-3ではMAIN本戦について、能力試合のwinnerをそのままブラケット進行へ使う。

## 実装内容

### Phase 2

`phase2_engine/models.py`

- MatchResolution追加
- CompetitionRun.match_simulation_results追加

`phase2_engine/main_tournament.py`

- optional match_resolver
- reference_year / generation_seed / match_id / team1 / team2をresolverへ渡す
- resolution score/winner整合検証
- score metadata保存
- full detail sink

`phase2_engine/engine.py`

- `TournamentEngine(repo, main_match_resolver=...)`
- MAINへresolverを注入
- CompetitionRunへfull match resultsを蓄積

`phase2_engine/result_view.py`

- embedded ability result自動読込
- explicit ability scoreとの衝突検出
- tournament matchとのteam/winner整合検証

`phase2_engine/results.py`

追加出力:

- ability match summary
- batter game stats
- pitcher game stats
- team game stats
- match events

### game_core

`game_core/tournament_bridge.py`

AbilityMainMatchResolverを追加。

同一school/year/seedのTeamMatchInputをcacheする。

## Integration test

実データから

- MAINのみの大会
- 同一都道府県内の硬式加盟校8校

を動的に選択。

8校single eliminationなので

- non-bye 7試合
- ability results 7件
- champion 1校

を検証した。

## 確認項目

- 全7試合score_source=ability_model_v1
- ability winnerが次ラウンドへ進む
- final match winner = CompetitionOutcome champion
- CompetitionRunに7 MatchSimulationResult保持
- 各matchに18 batter GameStats
- 各matchに2 team GameStats
- event runs = final score
- ResultView引数なしでability score表示
- embedded result conflict検出
- team input cache=8校
- same seed full tournament完全再現
- 保存CSV件数一致
- resolver未指定時はlegacy behavior維持

## GitHub Actions

初回統合CI:

- Python 3.12
- `Ran 429 tests in 11.794s`
- **OK**

Stage 13C-3専用テスト: 9件。

## Scope

Stage 13C-3で能力モデルへ移行したのはMAIN本戦のみ。

seed event / qualifier等は既存resolverのまま。

これは移行途中の仕様であり、前段も最終的には同じMatchResolution契約へ展開できる。

## 次工程候補

1. Stage 13C-4: pre-MAIN / SeasonOrchestrator接続
2. GameStats SQLite persistence
3. Stage 13D: 個人成績read model
4. 大会・シーズン・通算ランキング
