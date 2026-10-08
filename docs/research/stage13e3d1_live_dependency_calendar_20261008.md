# Stage 13E-3D-1 Live Dependency / Stage Calendar 実装報告

作成日: 2026-10-08

## 実装

新規:

- data/schedules/2026/competition_stage_calendar.csv
- phase2_engine/stage_calendar.py
- phase2_engine/live_season_dependency.py
- tests/test_stage13e3d1_live_dependency_calendar.py

更新:

- phase2_engine/paths.py
- phase2_engine/__init__.py
- phase2_engine/premain_runtime_composite.py

## Stage calendar

2026 pre-MAIN stage 49件を全件登録。

- verified: 0
- research_pending: 49
- explicitly_excluded_from_main_calendar: 26
- not_structured_separately: 23

既存MAIN calendarをpre-MAINへ自動流用しない。

pending stageは空date listへ変換されるため、
ScheduledCompetitionRuntimeはcalendar gapで停止する。

## Same-year access dependency

LiveSeasonDependencyRuntimeStateを追加。

destination annual templateは保持するが、
source dependency完了前はdestination runtimeを作らない。

source完了後にcompetition_access_rulesを解決し、

- direct_main_entry_school_ids
- seed_event_bypass_school_ids

へ結果を注入してdestinationをactivateする。

## Result release date

初回実装では宮城夏大会の内部bracketが公式7/28より前にcompleteし、
CMP000077秋大会が早期activateした。

原因:

generic wave schedulerは公式12試合日すべてを使う必要がなく、
7round分のwaveを先頭日から消化できるため。

修正:

same-year dependencyのresult release dateをsource season_calendarの最終game_dateへ固定。

宮城では7/28。

runtimeが早くcompleteしても7/28まではdestinationをmaterializeしない。

## Composite single-match fix

invalid date dependency testで、
FMT003のBlockForestRuntimeStateを1試合ずつresolveする経路に既存分岐漏れを検出。

_PhaseRecord.resolve_match()でBlockForestRuntimeState.block_runtimesを探索するよう修正。

これによりcomposite qualifierのdate-by-date executionが可能になった。

## 実データ回帰

### 宮城

- source: CMP000029
- rule: ACR000002
- destination: CMP000077

7/27時点: destination runtimeなし。

7/28 source result release:
秋大会へ夏優勝校をdirect_main_entryとして注入。

live destination完了後のCompetitionRunは、
同一direct entryを設定したlegacy TournamentEngine.run()と完全一致。

### 三重

- source: CMP000045
- rule: ACR000014
- destination: CMP000116

夏優勝校をseed_event_bypassへ注入。

MAIN direct entryにはしない。

live destination完了後CompetitionRunはlegacyと完全一致。

## Guards

- source dependency未完了: destination非生成
- external dependency: waiting_external_dependency
- unsupported selector/action: blocked
- destination初回日 <= source release date: blocked_date_dependency
- pending pre-MAIN stage: calendar gap

## Automated validation

Stage 13E-3D-1専用テスト: 7件。

full suite:

- Python 3.12
- Ran 533 tests in 21.850s
- OK

## 次工程

Stage 13E-3D-2で

- qualification_rules
- regional_feeder_rules
- regional_qualification_playoffs

をlive dependency graphへ接続する。
