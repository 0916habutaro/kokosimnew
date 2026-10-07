# ADR-003 Playerと能力・状態・成績を分離する

- Status: Accepted
- Date: 2026-10-07

## Context

選手能力は成長する。疲労や怪我は一時的で、打率やERAは結果である。

## Decision

次を分離する。

- Player: 人物・所属・学年
- PlayerAbilitySnapshot: その時点の基礎能力
- PlayerCondition: 疲労・調子・怪我
- PlayerGameStats / SeasonStats: 実績成績

## Consequences

- 年度・時点ごとの能力履歴を残せる。
- 疲労で基礎能力を破壊しない。
- 成績から能力へ逆流する設計を避けられる。
