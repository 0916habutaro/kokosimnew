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

Stage 13C-1の3configは `design_contract` であり、打席結果確率などのバランス値はまだ含めない。

## 方針

- 実スコアoverrideは常に最優先
- 能力モデルは `ability_model_v1`
- `generated_v1` は移行用fallback
- TeamStrength単一値から直接得点を作らない
- rate statsを正本保存しない
- 試合結果にはconfig id / revision / canonical SHA-256を保持する
