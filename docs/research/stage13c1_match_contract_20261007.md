# Stage 13C-1 能力ベース試合・イベント・個人成績 contract 実装報告

作成日: 2026-10-07

## 目的

Stage 13Bまでに完成した

- Player
- PlayerAbilitySnapshot
- SchoolIntakeProfile
- StartingLineup
- PitchingStaff
- TeamStrengthSnapshot

を、能力ベース試合へ接続する前に入出力契約を固定する。

Stage 13C-1では確率・得点分布の調整は行わず、後続実装が依存する境界だけを正本化した。

## 新規config

### match_simulation_v1.json

固定内容:

- score_source = ability_model_v1
- team1 = top offense
- team2 = bottom offense
- 完了試合tie禁止
- 大会ルールによるinning overrideを許可
- simulatorがscoreとwinnerを所有
- ResultView precedence
- RNG namespace
- TeamStrength単一値からの直接得点bonus禁止

### event_catalog_v1.json

最小12 event type:

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

各eventにAB判定・hit value・default outsを機械可読で保持する。

### game_stats_contract_v1.json

保存するcountを

- batter
- pitcher
- team

に分離。

率指標は保存しない。

## Python contract

`game_core/match_contract.py`

追加:

- TeamMatchInput
- MatchSimulationInput
- MatchEvent
- BatterGameStats
- PitcherGameStats
- TeamGameStats
- MatchSimulationResult
- MatchContractProvenance

## 13Bとの接続

テストでは実データmasterから2校を選び、

```
PlayerRosterGenerator
 -> SchoolAwarePlayerAbilityGenerator
 -> TeamStrengthGenerator
 -> TeamMatchInput
```

を実際に通してMatchSimulationInputを構築した。

これにより13C-1のcontractが架空のstubだけでなく、現在の13B-4出力を直接受けられることを確認した。

## Reconciliation

MatchSimulationResult validatorで以下を検証する。

- scoreとwinner / loser
- scoreとTeamGameStats.runs
- scoreとevent runs
- team runsとbatter runs
- team hitsとbatter hits
- team runsとopponent pitcher runs_allowed
- team hitsとopponent pitcher hits_allowed
- team batter PAとopponent pitcher BF
- event batter / pitcherのroster所属
- pitcher playerのprimary_position=P
- config provenance

## ResultView接続

`phase2_engine/result_view.py` を後方互換のまま拡張した。

優先順位:

1. override
2. ability_model_v1
3. generated_v1

ability scoreがTournamentEngineのwinnerと矛盾した場合は既存winner consistency validationで失敗する。

これはStage 13C-2以降で、試合シミュレータ結果をTournamentEngineへ同期してからResultViewを作るべきことを保証する。

## 個人成績

### batter

整数countのみ保存。

PA式:

`PA = AB + BB + HBP + SF + SH`

### pitcher

投球回は `outs_recorded` を保存し、表示時に回数表記へ変換する。

### rate stat

保存しない:

- AVG
- OBP
- SLG
- OPS
- ERA
- WHIP

Stage 13Dのread modelでcountから導出する。

## RNG

namespace:

- match_v1
- plate_appearance_v1
- event_v1

打席ロジック変更が別試合・別打席へ不要に波及しにくい構成を固定した。

## GitHub Actions

初回PR検証:

- Python 3.12
- 401 tests
- `Ran 401 tests in 8.390s`
- OK

Stage 13C-1追加contractテストは19件。

## 次工程

Stage 13C-2。

実装対象:

1. batter vs pitcher確率モデル
2. base/out state
3. inning progression
4. lineup rotation
5. pitcher usage / replacement
6. game ending
7. event -> stats集計
8. ability差と勝率・得点分布の大量監査
