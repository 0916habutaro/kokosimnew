# Stage 13E-3A pre-MAIN runtime primitives

作成日: 2026-10-08

## 目的

Stage 13E-2でMAIN-only大会はlazy / resumableになった。
Stage 13E-3Aではpre-MAINの共通競技要素をruntime化し、まず最頻出のFMT001 qualifier→MAIN graphをincremental executionへ移す。

## 分割方針

pre-MAINは26 format modelを持ち、複合repechage・league・seed eventを一度に変更すると回帰範囲が大きい。

Stage 13E-3を以下へ分割する。

- 13E-3A: 共通runtime primitive + FMT001 qualifier→MAIN
- 13E-3B: FMT002〜025、FMT006、seed event、gate graphのcompetition接続

## Runtime primitives

### SingleEliminationRuntimeState

既存 run_single_elimination_ranking() と同一の

- draw namespace
- match_id
- round number
- bye
- ranking tie-break namespace

を維持する。

prepare時にはwinnerを生成しない。
ready matchだけresolveできる。

### SingleRoundGateRuntimeState

既存 run_single_round_gate() と同じ

- gate draw
- match_id
- odd entrant bye
- winner order

をlazy化する。

### RoundRobinRuntimeState

既存 run_round_robin() と同じ全組合せを先に生成するが、winnerはresolve時まで空。

completed matchだけwins/lossesへ反映し、全試合終了後に既存tiebreak namespaceでrankingを確定する。

### BlockForestRuntimeState

balanced_partition()でrepresentative blockを生成し、各blockをSingleEliminationRuntimeStateとして保持する。

blockごとのwinnerがqualifier outputになる。

## FMT001 qualifier runtime

QualifierMainRuntimeStateは各stage groupについて

eligible entrants
→ output_slots
→ BlockForestRuntimeState

を作る。

qualifier中はmain_runtime=None。

全groupがcompleteになった時点で

qualifier outputs + direct MAIN entries
→ main entrants
→ MainTournamentRuntimeState

を初めて生成する。

## Future result

qualifier prepare時点:

- MatchResolver call = 0
- pre-MAIN winnerなし
- MAIN bracketなし
- MAIN entrant listなし

match解決後だけMatchSimulationResult sinkへdetailを追加する。

## Compatibility

Stage 13E-3Aの最重要条件:

同一AnnualCompetitionInput / seedについて

legacy TournamentEngine.run()
==
prepare_qualifier_main_runtime().resolve_all()

となること。

北海道春 CMP000004 でCompetitionRun.to_dict()全体を比較し完全一致を確認する。

## 現在の対応graph

- BRANCH_QUALIFIER(FMT001) → MAIN
- PRELIMINARY_QUALIFIER(FMT001) → MAIN

現在未対応:

- FMT006
- FMT002〜005 / 007〜025
- SEED_EVENT → MAIN
- SEED_EVENT → QUALIFIER → MAIN
- SEED_EVENT → FIRST_TOURNAMENT → MAIN

ただし必要なsingle elimination / gate / round robin / block forest primitiveは3Aで用意済み。
