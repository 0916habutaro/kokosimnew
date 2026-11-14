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

groupごとのoutput_slotsとeligible entrant数から `fmt006_pool_plan` で

- 4校pool数
- 3校pool数
- poolに入らずに進む学校の数（チームが少なく組めないときだけ）

を決定する。

（2026-11-14 改定）その年のチーム数から組む。組の1位は代表、残りの枠は2位から：
2位どうしの補充代表決定戦の数は「2位の数 −（残りの枠）」で、3校の組の2位を先に、
足りなければ4校の組の2位をあてる（`fmt006_qualifiers`）。組はできるだけ少なく
（4校の組を多く）して、決定戦が2位の数の半分に収まる組み方を選ぶ。2026年の
チーム数（代表の数の2倍）では、これまでの「4校pool上位2校・3校pool首位が直接、
3校pool2位が決定戦」と同じになる。

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
