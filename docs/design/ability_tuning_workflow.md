# 能力調整ワークフロー

## 目的

「なんとなく数値を変えた」状態を防ぎ、後から変更理由と影響範囲を追跡可能にする。

## 標準フロー

1. 問題を監査値で確認
2. 変更前の分布を保存
3. 変更対象JSONと理由を明記
4. revisionを増やす
5. golden seedを再生成
6. 大量生成監査
7. 変更後分布を保存
8. 期待外の変化がないか確認
9. tuning log作成
10. PR

## tuning log

`docs/tuning/stage13b_*.md`

最低限記録する。

- 対象config_id / revision
- 変更前
- 問題
- 仮説
- 変更値
- 変更後
- 副作用
- 採用/却下判断

## 大量監査

最低限:

- 全体平均
- 中央値
- 標準偏差
- P1 / P5 / P25 / P75 / P95 / P99
- 学年別
- 守備位置別
- 投手/野手別
- 学校別team strength分布

実装が進んだら:

- 打率
- OPS
- 得点
- ERA
- 奪三振率
- 四球率

などの試合結果分布も対象にする。

## Golden seed

基準seedを固定し、代表校を数校選ぶ。

目的:
- unrelatedな能力まで変わっていないか
- player_idが意図せず変わっていないか
- 学校強度が極端に変わっていないか

を確認する。

## version / revision

### config_id v2へ上げる
- 能力の意味変更
- 単位変更
- フィールド削除
- 根本的な計算式変更

### revisionのみ上げる
- 平均
- 標準偏差
- weight
- clamp
- 閾値

ただしrevision変更でも生成結果は変わる。
そのためsnapshotにはcanonical_config_sha256も記録する。

## コードと調整値

Python:
- アルゴリズム
- validation
- データ変換

JSON:
- 平均
- 標準偏差
- weight
- threshold
- 表示帯

を原則とする。
