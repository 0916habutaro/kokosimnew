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

`audits/phase3/stage13c2/stage13c2_match_distribution_20261007.csv`

3seed × 各1,000試合。

初期guardrailはテストで固定するが、現実校正時には根拠データとともにrevisionを上げて更新する。
