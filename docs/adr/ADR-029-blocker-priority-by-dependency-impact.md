# ADR-029: full-season blockerの優先度はdownstream dependency impactで決める

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3F-1

## Context

competition_stage_calendarには49件のresearch_pending stageがある。

単純に47大会分の日付を上から調査すると、

- 全国大会を止める秋予選
- 春地区だけを止める県予選
- 同年後続を持たない大会

が同じ優先度になる。

さらに年末E2E実行により、
research_pending stage以外にも

- CMP000079のstage未構造化疑い
- CMP000095 / CMP000113のdependency resolution failure

が発見された。

したがって「未調査日付件数」だけでは
年間完走への最短経路を示せない。

## Decision

blockerをruntime originで分類する。

- pending_pre_main_calendar
- calendar_gap_without_pending_stage
- dependency_resolution_failure
- upstream_dependency
- runtime_blocked
- incomplete_active

research actionはdownstream impactで優先する。

### P0_national_chain

未解消だと同年全国大会がblocked。

### P1_regional_chain

未解消だと地区大会がblockedするが、
同年全国大会には波及しない。

### P2_local_only

同年dependency destinationなし。

同tierでは、

1. dependency/structure blocker
2. stage date research

の順とする。

理由は、前者が残る状態では日付を登録してもruntimeがstageまで到達しないため。

## Consequences

### Positive

- 調査順を年間完走への効果で決定できる
- hidden structural defectを日付不足へ誤分類しない
- upstream waitを直接blockerと区別できる
- Jingu unblockに必要な作業をP0へ集中できる
- audit再実行で改善量を定量比較できる

### Trade-offs

- 同じcompetitionに複数actionが付く場合がある
- dependency graph変更でpriorityは再計算が必要
- P2でもゲーム体験上重要な大会が後順位になる

## Evidence

2026-12-31 E2E:

- complete 98
- calendar_gap 46
- blocked 2
- waiting_dependency 16

research_pending stage:

- P0 28
- P1 20
- P2 1

additional actions:

- P0 structure 1
- P1 dependency resolution 2

final action queue:

- P0 29
- P1 22
- P2 1
- total 52

## Follow-up

Stage 13E-3F-2でP0から修正し、
同じaudit seedで年末resultを再比較する。
