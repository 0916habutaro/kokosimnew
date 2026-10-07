# Ability configuration

Stage 13B以降の能力生成・学校能力算出で使用する、機械可読の調整値を置く。

## 正本

- `ability_catalog_v1.json`: 能力IDと意味。意味変更は原則v2。
- `ability_scale_v1.json`: 1〜100尺度・S〜G表示。
- `player_generation_v1.json`: baseline選手能力生成の分布・namespace。
- `school_intake_v1.json`: 合成program/cohort入部品質と能力調整幅。
- `team_strength_v1.json`: 選手→学校能力の集約重み。

## version と revision

`config_id` の v1/v2 は**意味・構造の互換性**を表す。

- 能力の意味変更
- フィールド削除
- 単位変更
- 計算方式の根本変更

は v2 を作る。

一方、平均・標準偏差・重みのバランス調整は同じconfig_idの `revision` を増やす。

ただし数値だけの変更でも生成結果は変わるため、セーブデータや能力snapshotには次を保存する。

- config_id
- revision
- canonical_config_sha256

## 暫定値

`status=design_default_not_tuned` は、実装開始用の暫定値であり実データ校正済みを意味しない。

Stage 13B-2以降では大量生成監査を行い、変更前→理由→変更→変更後を `docs/tuning/` に残す。

## 禁止事項

バランス調整値をPythonコードへ新規に直書きしない。

学校masterへ固定の学校戦力や直接TeamStrength bonusを追加しない。学校差は選手生成・入部層を通して形成する。

コードにはアルゴリズムを、JSONには調整値を置く。
