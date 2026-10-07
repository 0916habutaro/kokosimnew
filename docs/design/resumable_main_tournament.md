# Stage 13E-2 Resumable MAIN Tournament Runtime

作成日: 2026-10-08

## 目的

Stage 13E-1ではゲーム内日付とmatch lifecycleを導入したが、TournamentEngine自体は大会を一括完走していた。

Stage 13E-2ではMAIN単独大会を対象に、

- bracket skeleton生成
- ready match抽出
- 1試合ずつ解決
- winnerの次round伝播
- 大会途中状態保持
- 最終CompetitionRun materialize

を分離する。

## Compatibility

既存:

`TournamentEngine.run()`

は変更しない。

追加:

`TournamentEngine.prepare_main_runtime()`

Stage 13E-2時点ではstage構成がMAINのみの大会を対象とする。

## MainTournamentRuntimeState

保持:

- competition_id
- reference_year
- generation_seed
- stage_id
- entrant_school_ids
- seed_assignments
- annual_seed_order
- initial_slots
- seed_slots
- bracket_size
- total_rounds
- RuntimeBracketMatch
- match_simulation_results
- eliminated_by_round
- champion / runner_up

## RuntimeBracketMatch status

### waiting

上流matchが未解決でparticipantが揃っていない。

### ready

team1 / team2が揃い、試合実行可能。

winner / loserは空。

### completed

MatchResolver実行済み。

winner / loser確定。

### bye

first round bye。

MatchResolverを呼ばずwinnerを自動伝播する。

## Bracket skeleton

MAIN bracket slot生成には既存

- ordered_seed_ids()
- generate_main_slots()

を再利用する。

match_idもlegacy runと同一:

```
{stage_id}-MAIN-R{round_no:02d}-M{match_no:03d}
```

これによりMatchSimulatorのRNG namespaceも従来と一致する。

## Winner propagation

resolve_match()後:

1. winner / loser記録
2. eliminated_by_roundへloser追加
3. ability detail保存
4. next_match_id / next_match_sideへwinner伝播
5. downstream matchのstatus再評価

両participantが揃った時点でwaiting→readyとなる。

## Lazy execution

### prepare

bracket skeletonだけ生成。

実試合についてMatchResolverは0回。

### resolve_match

指定したready matchだけ実行。

waiting / completed / byeは拒否。

### resolve_ready_round

現在readyな最小roundだけまとめて実行。

### resolve_all

legacy互換確認用。

全roundを順に解決し、最後にCompetitionRunを返す。

## CompetitionOutcome

大会完了前:

`to_competition_run()`

は拒否。

大会完了後に

- champion
- runner-up
- semifinalists
- quarterfinalists
- final ranking
- eliminated_by_round
- match_count
- bye_count

をlegacyと同じ規則で生成する。

同順位cohortのrandom ordering namespaceもlegacyと同じ。

## Ability match

MatchResolverにAbilityMainMatchResolverを渡した場合でも、prepare時点ではplayer generation / MatchSimulatorを呼ばない。

resolve_match()時に初めてAbilityMatchResolverを呼ぶ。

MatchSimulationResult detailは解決済みmatchだけmatch_simulation_resultsへ追加する。

## Winner override

annual.main_match_winner_overridesはMatchResolverより優先する。

override matchではMatchResolverを呼ばない。

## ScheduledMainTournamentRuntime

MAIN runtimeへgame_date_listを割り当てるadapter。

Stage 12 browse viewと同じ線形投影方式を使う。

API:

- scheduled_dates()
- matches_for_date()
- play_date()
- advance_through()
- public_snapshot()

### play_date

対象日のmatchだけを解決する。

同じ日に

- upstream match
- downstream match

が存在する場合は、upstream解決後にdownstreamがreadyになれば同日内で続けて実行する。

過去に必要な上流matchが未解決ならblockedとして例外にする。

## Future result

未実行matchでは

- winner
- loser

は空。

AbilityMatch detailも存在しない。

prepared future resultそのものを保持しない。

これはStage 13E-1との最大の違い。

## Current scope

Stage 13E-2:

- MAIN-only competition

まだ対象外:

- SEED_EVENT
- BRANCH_QUALIFIER
- PRELIMINARY_QUALIFIER
- FIRST_TOURNAMENT
- round robin / repechage等のpre-MAIN format
- prefectural→regional qualificationのincremental activation

これらはStage 13E-3でruntime化する。
