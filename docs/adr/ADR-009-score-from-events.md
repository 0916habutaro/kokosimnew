# ADR-009: 試合得点は打席eventの積み上げから生成する

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 13BでTeamStrengthを作成したため、学校戦力差からPoisson等で最終得点だけを生成する方法も可能である。

しかしこのゲームでは個人成績・大会ランキング・選手通算成績を閲覧対象にする。

最終得点だけ先に生成すると、後から作る打席eventや個人成績をscoreへ合わせる逆算処理が必要となり、二重の真実が生まれる。

## Decision

Stage 13C-2以降の能力モデルでは

```
PlayerAbility
 -> plate appearance
 -> base/out state
 -> runs
 -> GameStats
 -> final score
```

の順で生成する。

TeamStrengthはevent weightや守備・投手運用を補助するcomponentとして使うが、総合値から直接最終得点を生成しない。

MatchSimulationResultはStage 13C-1 reconciliationを必須とする。

## Consequences

### 利点

- scoreと個人成績が自然に一致する
- 打者・投手能力を直接試合へ反映できる
- 将来のBox Score・ランキング・通算成績へ接続しやすい
- event確率だけをrevision管理して調整できる

### 注意点

- 最終scoreだけ生成する方式より計算量が大きい
- 走塁・交代・失策・自責点のルールを段階的に実装する必要がある
- v1の簡略化を現実ルールそのものと解釈しない

## Initial scope

Stage 13C-2 v1では

- 9人打順
- 投手staff順継投
- 12打席event
- base/out state
- 9回＋延長
- walk-off

までを実装する。

盗塁、代打、守備交代、大会固有タイブレーク等は後続revisionとする。
