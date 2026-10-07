# ADR-004 能力乱数namespaceを能力単位で分離する

- Status: Accepted
- Date: 2026-10-07

## Context

1つのRandom streamで全能力を生成すると、途中に1回乱数呼び出しを追加しただけで後続能力がすべて変わる。

## Decision

能力・trait・球種ごとにversion付きnamespaceを使う。

例:

- player_ability_v1:{year}:{player_id}:contact
- player_ability_v1:{year}:{player_id}:fielding
- player_pitch_v1:{year}:{player_id}:slider

生成snapshotには使用したconfig_id / revision / canonical config SHA-256も保存する。

## Consequences

- contact生成を調整してもfieldingが不必要に変わりにくい。
- namespaceの意味を変える場合はv2を使う。
- seedだけでは完全再現情報として不足し、config情報も必要になる。
