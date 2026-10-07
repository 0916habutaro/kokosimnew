# Stage 13E-3B-1 FMT006 pre-MAIN runtime

作成日: 2026-10-08

## 目的

Stage 13E-3Aでsingle elimination / gate / round robin / block forestの共通runtime primitiveを導入した。

Stage 13E-3B-1ではFMT006をcompetition runtimeへ接続し、

3〜4校POOL_RR
→ 4校pool上位2校は直接通過
→ 3校pool首位は直接通過
→ 3校pool2位はCROSS_PLAYOFF
→ 全代表確定
→ MAIN activation

を未来結果なしで段階実行する。

## Pool preparation

groupごとのoutput_slotsとeligible entrant数から、既存 _solve_3_or_4_pool_plan と同じ条件で

- 4校pool数
- 3校pool数

を決定する。

annual.group_pool_assignments が与えられた場合は年次overrideを優先し、各eligible teamがちょうど1回含まれること、各poolが3校または4校であることを検証する。

## POOL_RR runtime

各poolはRoundRobinRuntimeStateとしてprepareする。

prepare時点では全対戦カードは存在するが、

- winner
- loser
- score
- detailed result

は存在しない。

resolve時のみMatchResolverを呼ぶ。

## Cross playoff activation

CROSS_PLAYOFFはpool phase完了前には作らない。

全pool完了後にrankingを確定し、

- 4校pool: 上位2校をdirect
- 3校pool: 1位をdirect、2位をrunner-up cohort

とする。

runner-up cohortを既存namespace

`{competition_id}:{stage_id}:{group_id}:cross_playoff_draw`

でshuffleし、2校ずつCROSS_PLAYOFFへ入れる。

奇数の場合は最後の1校をbyeとする。

## Match compatibility

CROSS_PLAYOFF match ID:

`{stage_id}-{group_id}-CROSS_PLAYOFF-M{match_no:03d}`

RNG namespace:

`{competition_id}:{stage_id}:{group_id}:CROSS_PLAYOFF:M{match_no}:{team1}:{team2}`

を既存run_head_to_head()と完全一致させる。

## MAIN activation

全stage groupのFMT006 runtimeがcompleteになるまでMAIN runtimeは生成しない。

qualifier output + direct MAIN entriesを統合した時点でMainTournamentRuntimeStateを生成する。

## Compatibility

神奈川春 CMP000095 で以下を比較する。

- random winner legacy run vs lazy run
- detailed MatchResolution legacy run vs lazy run
- annual group_pool_assignments override legacy run vs lazy run

CompetitionRun.to_dict()全体が完全一致しなければならない。

## Current scope

対応:

- FMT001 qualifier→MAIN
- FMT006 qualifier→MAIN

次工程:

- FMT002〜005 / 007〜025の複合phase composition
- SEED_EVENT
- FIRST_TOURNAMENT
