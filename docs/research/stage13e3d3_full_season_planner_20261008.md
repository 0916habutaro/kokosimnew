# Stage 13E-3D-3 Full-season Live Graph Planner 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/live_season_planner.py
- tests/test_stage13e3d3_full_season_planner.py

更新:

- phase2_engine/live_season_dependency.py
- phase2_engine/__init__.py

## planner coverage

2026 competition master:

- total: 162
- spring: 56
- summer: 50
- autumn: 56
- season_calendar: 162 / 162

strategy:

- senbatsu_bootstrap: 1
- summer_area: 49
- structural: 81
- deferred_structural: 13
- dependency_aggregate: 18

total 162。

## dependency graph

family:

- root: 131
- access: 13
- qualification: 2
- regional_feeder: 16

unique dependency edge: 165

topological sort: 162 / 162
cycle: 0

## external context

current-year graph外のaccess rule: 8

- prior autumn prefectural: 6
- prior autumn regional: 1
- newcomer tournament: 1

全8件を既存SeasonOrchestrator compatible bootstrapでPASS。

unresolved: 0
warning: 0

代表確認:

- CMP000094 東京春 direct=64
- CMP000128 沖縄秋 direct=4

## deferred structural

current-year access result待ち13大会を空templateとしてplan。

CMP000016東京秋:

planner時点:

- entrants=[]
- direct=[]

1/1〜8/5 full runtime後:

- 東西東京夏優勝2校がdirect
- total entrants=232
- direct 2校はentrant setに含まれる
- PRELIMINARY stage date pendingのためcalendar gap

future participant placeholderなし。

## full runtime startup

plan.build_runtime()のみで起動。

初期:

- templates: 162
- active root runtimes: 131
- waiting dependency: 31

手動annual inputの列挙は不要。

## full runtime progression

1/1から8/5まで自動進行。

- 49地方大会が各calendarで進行
- 49 winnerが揃う
- CMP000002夏全国を49 entrantsで自動materialize
- CMP000036/037結果からCMP000016をdeferred build

planner→runtime→dependency→annual materializationをend-to-endで確認。

## calendar safety

pre-MAIN stage calendar:

- research_pending: 49
- verified: 0

plannerもこの状態をそのままruntimeへ渡す。

未確認stageはcalendar gapとなり、
MAIN日程や架空日付を使用しない。

## Automated validation

Stage 13E-3D-3専用テスト: 7件。

full suite:

- Python 3.12
- Ran 544 tests in 34.753s
- OK

full-season回帰を追加したため、
3D-2時点よりsuite時間は増加した。

## 判断

Stage 13E-3D-3を採用する。

Stage 13E-3Dで目標としていた

- 大会間dependency live化
- national/regional fan-in
- annual template自動生成
- topological planning
- full-season graph startup

まで完了。

次工程は日程精度と永続化を優先する。
