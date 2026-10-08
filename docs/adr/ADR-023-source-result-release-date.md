# ADR-023: 大会間結果はsource公式最終試合日まで後続へ解禁しない

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3D-1

## Context

Stage 13E-3Cのgeneric schedulerはready frontierを日付へ割り当てる。

公式calendarには同じroundが複数日に分かれる大会があるため、
generic runtime内部では公式決勝日より前にbracketが完了する場合がある。

一方、夏大会優勝校を秋大会へ直接出場させる等の大会間依存では、
source resultを実大会終了前に後続へ渡してはいけない。

またpre-MAIN日程は既存season_calendarに含まれない大会が多く、
MAIN日程を自動fallbackすると事実と異なる日付を作る。

## Decision

同年access dependencyではsource result release dateを

max(source game_date_list)

とする。

game_date_listが無い場合のみruntime completed_onを使用する。

destination runtimeはrelease date到達前には生成しない。

さらにpre-MAIN stage calendar masterを別ファイル化し、
research_pending stageは空date listとしてschedulerへ渡す。

空date listはcalendar gapを意味し、
competition-wide MAIN日程へfallbackしない。

destination初回日がsource release date以前なら
blocked_date_dependencyとしてactivateを拒否する。

## Consequences

### Positive

- 夏大会優勝校が公式決勝前に秋大会へ出現しない
- MAIN日程をpre-MAINへ誤流用しない
- stage日程未調査をデータgapとして明示できる
- source→destinationのruntime lifecycleが実calendar順になる
- 後からverified stage datesへ置換しやすい

### Trade-offs

- generic source runtime自体は公式最終日前にcompleteになる場合がある
- dependency releaseとruntime completionを別概念として扱う必要がある
- pre-MAIN 49 stageの正確な日付調査は別途必要

## Follow-up

Stage 13E-3D-2でqualification_rules / regional_feeder_rulesへ同じrelease-date契約を適用する。
