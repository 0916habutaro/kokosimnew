# ADR-010: 大会構造と試合シミュレーションをMatchResolutionで分離する

- Status: Accepted
- Date: 2026-10-07

## Context

Phase 2のTournamentEngineは47都道府県の多様な大会方式を管理している。

Stage 13のMatchSimulatorは選手能力・打席event・個人成績を管理する。

TournamentEngineから直接MatchSimulatorやPlayerAbilityGeneratorを呼ぶ設計にすると、Phase 2がgame_coreの能力モデルへ強く依存し、大会方式と試合モデルを別々に変更しにくくなる。

## Decision

Phase 2に汎用 `MatchResolution` を置く。

TournamentEngineはoptionalな `main_match_resolver` を呼び、MatchResolutionだけを受け取る。

Stage 13側に `AbilityMainMatchResolver` を置き、

```
school_id
 -> roster
 -> ability
 -> team strength
 -> MatchSimulator
 -> MatchResolution
```

を担当させる。

Stage 13C-3ではMAINだけを対象にする。

## Consequences

### 利点

- Phase 2はgame_coreへ依存しない
- 既存random resolverをそのまま維持できる
- 年度実績overrideを維持できる
- 将来別の試合モデルも同じresolver契約へ差し替え可能
- 大会構造テストと能力試合テストを分離できる

### 制約

- 前段予選はStage 13C-3時点では従来resolver
- AbilityMainMatchResolverを明示的に注入しない限り能力モデルは使われない
- SeasonOrchestrator全体の標準化は後続工程

## Rejected alternative

TournamentEngine内部へPlayerRosterGenerator / PlayerAbilityGenerator / MatchSimulatorを直接組み込む案は採用しない。

大会構造層が能力モデルの設定・provenance・生成仕様を知る必要が生じるため。
