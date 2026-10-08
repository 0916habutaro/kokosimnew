# Stage 13E-3D-2 Qualification / Regional Live Dependency 実装報告

作成日: 2026-10-08

## 実装

更新:

- phase2_engine/live_season_dependency.py
- phase2_engine/__init__.py

追加:

- tests/test_stage13e3d2_qualification_regional.py

## dependency family追加

LiveSeasonDependencyRuntimeStateへ

- qualification_rules
- regional_feeder_rules
- regional_qualification_playoffs

を読み込む経路を追加。

公開resolution:

- LiveQualificationDependencyResolution
- LiveRegionalFeederDependencyResolution
- LiveRegionalPlayoffDependencyResolution

public_snapshot / summaryにも件数と解決内容を追加。

## qualification

59 ruleを2026 dataから読み込む。

winner selectorを実装。

全sourceの公式result release後にだけdestinationをactivate。

destination team_count一致も必須。

### 夏全国

49地方大会をlive進行。

全49 source resultが解禁される前はCMP000002 runtimeなし。

49代表確定後のみCMP000002を生成。

8/22まで進行しlegacy CompetitionRun完全一致。

### 神宮

QRL000050〜059の10winnerからCMP000003 annual entrantsを生成可能。

現行2026 calendarは個別game_date_list未確定のため、
本番live graphでは日程追加までcalendar gapになる設計を維持。

## regional feeder

SeasonOrchestrator._resolve_regional_feeders()の以下を移植。

- rank_range
- exclude_already_selected
- fill_to_quota
- national_invitational_participants
- direct
- playoff_candidate

### 四国春

徳島/香川/愛媛/高知のfinal ranking各上位2校を選出。

8 entrantsの順序がlegacy resolverと完全一致。

地区大会CompetitionRunもlegacyと完全一致。

## 近畿playoff

KPL2026A / KPL2026Bをlegacyと同一namespaceで決定。

synthetic completed source rankingを双方resolverへ入力し、

- feeder resolutions
- playoff winner
- final 16 entrants

完全一致。

## dependency lifecycle

destination statusにdependency_familyを追加。

source graphはaccess / qualification / regional_feederを共通取得。

現行2026 graphで複数familyが同一destinationへ重なるケースはない。

将来重複した場合は暗黙mergeせずblocked。

## Automated validation

Stage 13E-3D-2専用テスト: 4件。

full suite:

- Python 3.12
- Ran 537 tests in 25.255s
- OK

## 判断

Stage 13E-3D-2を採用する。

これにより同年主要大会間の

- access
- automatic qualification
- prefectural → regional feeder
- structural regional playoff

がLiveSeasonDependencyRuntimeStateで遅延materializeできる。

## 次工程

Stage 13E-3D-3でfull-season graph planningと
pre-MAIN stage calendarの実日付verified化へ進む。
