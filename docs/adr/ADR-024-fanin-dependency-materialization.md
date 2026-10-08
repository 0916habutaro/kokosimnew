# ADR-024: qualification / regional feederは全source解禁後にdestinationをmaterializeする

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3D-2

## Context

大会間依存には、1 source → 1 destinationだけでなく、

- 49地方大会 → 夏全国大会
- 4〜8県大会 → 地区大会
- 10秋代表大会 → 神宮

のようなfan-inがある。

sourceが一部だけ終了した時点でdestination bracketを生成すると、
未来の出場校をplaceholderで補う必要が生じる。

また県大会順位から地区大会へ進む場合、
複数ruleのdeduplicate・quota補充・playoffをすべて完了しなければ
正しいentrant orderを確定できない。

## Decision

qualification / regional feeder destinationは、
dependency family内の全sourceが

- runtime complete
- official result release date到達

の両方を満たすまでmaterializeしない。

全rule resolution後に一度だけAnnualCompetitionInputを構築する。

qualificationでは全winnerをrule順に集約する。

regional feederではlegacy SeasonOrchestratorと同じ順で

1. priority / feeder_rule_id sort
2. direct selection
3. exclude_already_selected
4. fill_to_quota
5. playoff_candidate収集
6. regional playoff

を適用する。

entrant countがcompetition.team_countと一致しない場合はactivateしない。

## Consequences

### Positive

- 未確定代表校をfuture stateへ出さない
- 夏全国49代表が全地方大会終了前に生成されない
- 地区大会entrant orderがlegacyと一致
- 近畿playoff結果を既存SeasonExecutorと一致させられる
- Jinguは10代表確定と試合日未確定を別状態として表現できる

### Trade-offs

- sourceの1大会でもcalendar gapになるとdestinationもwaitingする
- regional playoffはまだMatchResolver試合ではなくstructural selection
- full seasonを自動構築するにはannual template plannerが別途必要

## Follow-up

Stage 13E-3D-3でannual template / dependency graphの自動planningと
pre-MAIN stage calendarのverified化を進める。
