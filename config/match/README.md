# Match configuration

Stage 13C以降の能力ベース試合シミュレーションに関する機械可読contract・調整値を置く。

## Stage 13C-1

- `match_simulation_v1.json`
  - 試合入出力
  - winner ownership
  - innings policy
  - ResultView score source precedence
  - RNG namespace
- `event_catalog_v1.json`
  - 最小打席event type
  - AB判定
  - hit value
  - default outs
- `game_stats_contract_v1.json`
  - batter / pitcher / teamの保存count
  - reconciliation規則

## 試合の規定（段階3、2026-10-26）

- `game_rules_v1.json`
  - タイブレーク（10回から無死一・二塁。打順は続ける）
  - 得点差コールド（5回10点差・7回7点差。都道府県大会・地区大会で、本大会の決勝を除く。神奈川は準決勝から除く）
  - 試合ごとの規定は `game_core/tournament_bridge.py` の `AbilityMatchResolver.rules_for` が決め、`MatchSimulator.simulate(..., rules=...)` に渡す
  - 球数制限（`pitch_limit`：試合の日を含む7日間に500球まで）。投げた球数は年度の状態の `pitch_log`（選手 → 日 → 球数）に残し、`AbilityMatchResolver` が試合ごとに「あと何球投げられるか」を `simulate(..., pitch_allowances=...)` に渡す
- `match_simulation_v1.json`（revision 4。能力の効きと1打席の球数を夏の地方大会の実際の試合に合わせた。`game_definition.md` §11）
  - `pitch_count`：1打席の球数（打席の結果ごとに［最少, 上乗せの最大］）
  - `pitching_usage` の `starter_minimum_pitches`（残りがこれより少ない投手は先発させない）・`reliever_minimum_pitches`（これより少ない投手は投げさせない）・`emergency_pitcher_ability`（投手が足りず野手が投げるときの投手の能力）

## version / revision

意味・構造の破壊的変更はv2。

確率・係数・閾値などの調整は同じconfig_idのrevisionを上げる。

Stage 13C-1でcontractを固定した後、Stage 13C-2で `match_simulation_v1.json` をrevision 2へ更新した。

revision 2には以下の暫定調整値を含む。

- plate appearance base probability
- ability effect scale
- sacrifice bunt / fly
- baserunning
- pitching usage
- hard max innings

statusは `design_default_not_tuned`。実在高校野球へ校正済みではない。

## 方針

- 実スコアoverrideは常に最優先
- 能力モデルは `ability_model_v1`
- `generated_v1` は移行用fallback
- TeamStrength単一値から直接得点を作らない
- rate statsを正本保存しない
- 試合結果にはconfig id / revision / canonical SHA-256を保持する


## Stage 13C-2 audit

正本:

`audits/phase3/stage13c2/stage13c2_match_distribution_20261007.csv`（段階0で削除。ブランチ `archive/pre-cleanup-20261020` に残っている）

3seed × 各1,000試合。

初期guardrailはテストで固定するが、現実校正時には根拠データとともにrevisionを上げて更新する。
