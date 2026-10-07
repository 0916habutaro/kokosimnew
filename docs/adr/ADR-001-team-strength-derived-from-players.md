# ADR-001 学校能力は選手能力から算出する

- Status: Accepted
- Date: 2026-10-07

## Context

高校野球ゲームでは年度更新・卒業・起用変更により同じ学校でも強さが変化する必要がある。

## Decision

学校masterへ固定の打撃力・投手力・守備力を持たせない。

TeamStrengthSnapshotはPlayerAbilitySnapshotと起用情報から算出する。

学校ブランドや強豪補正も試合時能力へ直接加算しない。

## Consequences

- 3年生卒業後に自然に弱体化できる。
- エース不在・連投などを後段で反映できる。
- チーム力計算の重み調整が重要になる。
- 選手能力が未実装の間は正式team strengthを作れない。
