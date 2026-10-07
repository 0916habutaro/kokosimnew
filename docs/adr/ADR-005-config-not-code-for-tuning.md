# ADR-005 バランス調整値はコードではなくversion付き設定へ置く

- Status: Accepted
- Date: 2026-10-07

## Context

能力平均・標準偏差・チーム集約重みは調整頻度が高い。

Pythonへ直書きすると、アルゴリズム変更とバランス変更の差が追いにくい。

## Decision

調整値は `config/abilities/` のJSONへ置く。

Pythonは読み込み・validation・アルゴリズムを担当する。

意味変更はconfig_idのv2、数値調整はrevision増加で管理する。

## Consequences

- PRで数値差分を確認しやすい。
- コード変更なしで調整可能。
- JSON validationが必要。
- 変更後の大量生成監査を必須運用とする。
