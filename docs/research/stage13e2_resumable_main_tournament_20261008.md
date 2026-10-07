# Stage 13E-2 Resumable MAIN Tournament 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/tournament_runtime.py
- tests/test_stage13e2_resumable_main_tournament.py

更新:

- TournamentEngine.prepare_main_runtime()
- phase2_engine package exports

## Runtime

MainTournamentRuntimeState:

- waiting
- ready
- completed
- bye

bracket skeleton生成時点ではMatchResolverを呼ばない。

winner確定後にnext_match_id / next_match_sideへ伝播する。

## Scheduled runtime

ScheduledMainTournamentRuntimeでgame_date_listへ実試合を投影。

play_date()が呼ばれた日だけMatchResolverを実行する。

## Legacy equivalence

### random winner resolver

legacy:

TournamentEngine.run()

lazy:

prepare_main_runtime()
→ resolve_all()

CompetitionRun.to_dict()を完全比較し一致。

### AbilityMainMatchResolver

同じseed・同じ8校を別resolver instanceで実行し、以下を含め完全一致:

- match ids
- bracket
- winner / loser
- scores
- MatchSimulationResult
- events
- batter stats
- pitcher stats
- team stats
- final ranking

## Dedicated validation

Stage 13E-2専用テスト: 12件。

- prepare resolver 0 call
- single match propagation
- round incremental resolution
- random legacy exact equality
- ability legacy exact equality
- winner override priority
- bye auto propagation
- incomplete materialization rejection
- scheduled play_date lazy call
- scheduled advance_through
- future winner hidden
- waiting match resolve rejection

## GitHub Actions

- Python 3.12
- Ran 493 tests in 19.255s
- OK

## 判断

Stage 13E-2 MAIN runtimeを採用する。

Stage 13E-1では内部prepared future resultが存在したが、Stage 13E-2 MAIN runtimeでは未実行matchの結果自体がまだ存在しない。

次工程Stage 13E-3ではpre-MAIN formatをruntime化し、

- qualifier
- seed event
- gate
- MAIN activation

まで大会全体をincremental executionへ移行する。
