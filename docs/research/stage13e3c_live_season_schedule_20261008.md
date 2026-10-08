# Stage 13E-3C Live Season Schedule Runtime 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/competition_schedule_runtime.py
- phase2_engine/live_season_runtime.py
- tests/test_stage13e3c_live_season_schedule.py

更新:

- phase2_engine/engine.py
- phase2_engine/__init__.py

## ScheduledCompetitionRuntime

competition runtimeのready frontierだけへ日付を割り当てる。

play_date()までMatchResolverは呼ばない。

当日分解決後、次のdependent waveを初めてscheduleする。

## LiveSeasonRuntimeState

AnnualCompetitionInputからlive competition runtimeを作成し、
current_dateで進行する。

対応操作:

- today_matches
- matches_for_date
- play_today
- next_day
- advance_to
- advance_through

completed matchだけからschool_recordsを作る。

competition完了前はchampionを公開しない。

## 日付source

- runtime_wave_v1
- stage_date_list
- calendar_gap

pre-MAINの正確な日付が判明している場合はstage_date_listsを利用する。

日付不足ではresolverを実行せず停止する。

## 実大会回帰

### 北海道春 CMP000004

BRANCH_QUALIFIER → MAINを日付進行。

stage-specific qualifier dates + MAIN datesを使い、
最終CompetitionRun.to_dict()がlegacyと完全一致。

### 岐阜秋 CMP000110

SEED_EVENT → FIRST_TOURNAMENT → MAINを日付進行。

初回実装ではbye propagationによって一部MAIN round2がround1と同時にREADYになり、
schedulerが同日に先行処理したためCompetitionOutcomeの同順位内順序だけがlegacyと差分になった。

勝敗・seed assignments・MAIN entrants・StageExecutionは一致していた。

修正としてstage_code + phase_code + group_id単位のminimum roundだけを
frontierとしてscheduleするよう変更。

修正後はCompetitionOutcomeを含むCompetitionRun.to_dict()が完全一致。

## Season runtime validation

MAIN-only 8校fixture:

- prepare時 resolver 0 call
- 4/1 round1のみ
- 4/2 round2のみ
- 4/3 finalのみ
- 完了時legacy完全一致

midseason start:

- start_dateより前だけresolver実行
- start_date当日matchはpending
- future winnerなし

calendar exhaustion:

- date不足時にREADY matchをcalendar_gapとして公開
- winnerなし
- match_dateなし
- competition未完了

## Automated validation

Stage 13E-3C専用テスト: 8件。

full suite:

- Python 3.12
- Ran 526 tests in 13.378s
- OK

## 判断

Stage 13E-3Cを採用する。

これで、

competition structure
→ lazy match runtime
→ date schedule
→ current_date
→ MatchResolver

が一本のruntime pathになった。

ただし既存2026 season_calendarはpre-MAIN stage dateをすべて保持しているわけではない。

次工程Stage 13E-3Dではstage calendarの構造化と、
SeasonExecutorが持つsource/destination competition dependencyをlive executionへ接続する。
