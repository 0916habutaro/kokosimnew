# ADR-021: SEED_EVENT結果依存の後続stageを完了後にactivateする

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3B-3

## Context

seed eventの結果は後続stageの構造そのものを変える。

例:

- 岐阜秋ではseed校がFIRST_TOURNAMENTを免除する。
- 愛媛秋ではseed校を県大会予選の別blockへ分散する。
- seed-only大会ではseed順位がMAIN drawへ影響する。

SEED_EVENT開始時点で後続stageを生成すると、未来のseed対象校を内部的に確定する必要が生じる。

## Decision

後続stageは依存するstageが完了するまで生成しない。

- seed result確定前: gate / qualifier / MAINなし
- seed確定後: gateまたはqualifierを生成
- gate / qualifier完了後: MAINを生成

seed model内部でも同じ原則を適用する。

- FMT018/020 secondary phaseはPRIMARY_SEED_KO完了後
- FMT019/021 ranking/cross phaseはprimary league完了後

legacy一括runは互換性oracleとして残す。

## Consequences

### Positive

- 大会開始時に未来のseed校・gate出場校・MAIN entrantを生成しない。
- game date runtimeからstage単位・試合単位で安全に進行できる。
- seed eventの本来の目的を後続drawへ正しく反映できる。
- legacyとの完全一致を自動検証できる。

### Trade-offs

- runtime graphがstage activation責務を持つ。
- annual ranking overrideは既知入力として扱うため、通常のsimulation結果とは区別が必要。
- season schedule接続では未activate stageの日程表現を扱う必要がある。

## Follow-up

Stage 13E-3Cでcompetition runtimeをSeasonRuntimeStateへ統合し、ゲーム内日付による試合発火とstage activationを結合する。
