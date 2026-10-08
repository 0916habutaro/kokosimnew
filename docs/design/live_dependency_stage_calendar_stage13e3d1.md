# Stage 13E-3D-1 live dependency / pre-MAIN stage calendar

作成日: 2026-10-08

## 目的

Stage 13E-3Cで、単一competitionについて

- lazy competition runtime
- game date
- current_date
- MatchResolver

を接続した。

3Dでは大会間依存をlive化する。
最初の3D-1では、同年の competition_access_rules による

- 夏大会優勝 → 秋大会直接出場
- 夏大会優勝 → 秋SEED_EVENT免除＋seed付与
- 同年全国大会参加 → 春県大会推薦

のような依存を対象とする。

また、既存season_calendarがMAIN日程中心であることを明示するため、
2026 pre-MAIN stage calendar masterを新設する。

## competition_stage_calendar.csv

2026のpre-MAIN stageを全49件登録する。

内訳:

- BRANCH_QUALIFIER: 35
- SEED_EVENT: 9
- FIRST_TOURNAMENT: 1
- PRELIMINARY_QUALIFIER: 4

現時点の既存Stage12G等の日程はMAIN scope中心であるため、
pre-MAINへ自動流用しない。

全49件を date_status=research_pending とする。

season_calendar notesで地区予選・支部予選・前段予選・seed event等が
MAIN日程から明示的に除外されている26件は

calendar_relation=explicitly_excluded_from_main_calendar

として記録する。

残り23件は

calendar_relation=not_structured_separately

とする。

未確認stageはdate_listを空欄に保つ。

## stage calendar loader

phase2_engine/stage_calendar.py

提供API:

- load_competition_stage_calendar()
- validate_competition_stage_calendar()
- stage_date_lists_by_competition()

validationでは

- pre-MAIN stage全件coverage
- stage_id / competition_id / stage_code一致
- duplicate禁止
- date_status whitelist
- verifiedはdate_list必須
- research_pendingはdate_list禁止
- ISO date / sort / duplicate検証

を行う。

include_pending=Trueではresearch_pending stageを空listとして返す。

これによりScheduledCompetitionRuntimeはcompetition-wide MAIN日程へfallbackせず、
calendar gapとして停止する。

## LiveSeasonDependencyRuntimeState

同年access dependencyをsource competition完了までmaterializeしない。

annual_templatesにはsource/destination両方の構造入力を保持するが、
destination runtimeはdependency解決前には生成しない。

### activation

1. source competitionをlive実行
2. source result確定
3. competition_access_rulesを解決
4. destination AnnualCompetitionInputをcopy
5. resolved school idをdirect_main_entry_school_idsまたはseed_event_bypass_school_idsへ注入
6. destination runtimeを初めてprepare
7. destination calendarへ接続

### selectors

3D-1で対応:

- winner
- participant_from_destination_prefecture
- participants_from_destination_prefecture

### actions

3D-1で対応:

- grants_main_entry=yes
- bypass_branch_seed_event_assign_seed

未対応selector/actionはUNSUPPORTEDとしてblockする。

## dependency release date

単純なwave schedulerでは、公式game_date_listに同一roundの複数試合日がある場合、
内部bracketが公式最終日より前に完了する可能性がある。

しかし後続大会へchampionを渡せるのはsource大会の実際の終了後である。

そのためaccess dependencyのresult release dateは

max(source season_calendar.game_date_list)

とする。

calendar dateが無い場合のみ、runtime completed_onの最大日をfallbackとする。

これにより宮城夏CMP000029のwinnerは7/28まで秋CMP000077へ解禁しない。

## date dependency guard

destinationの最初のscheduled dateがsource result release date以前の場合、
destinationをactivateしない。

status:

blocked_date_dependency

として保持する。

過去日へ遡って後続大会を実行することはない。

## nested BlockForest single-match resolve

3Dのgame-date executionでFMT003等を1試合ずつresolveした際、
_PhaseRecord.resolve_match()がBlockForestRuntimeStateにmatches属性を期待していた。

contains_matchと同様にblock_runtimesを探索するよう修正した。

これによりcomposite qualifierも日付単位resolve可能。

## 実データ検証

### 宮城

CMP000029 夏宮城大会
→ ACR000002
→ CMP000077 秋宮城県大会

7/28のsource calendar最終日までCMP000077は未生成。

winner確定後、

direct_main_entry_school_ids=[夏優勝校]

を注入して秋大会をactivate。

stage date fixtureで最後までlive進行し、
destination CompetitionRunは同じdirect entryを明示したlegacy runと完全一致。

### 三重

CMP000045 夏三重大会
→ ACR000014
→ CMP000116 秋三重県大会

夏優勝校を

seed_event_bypass_school_ids

へ注入する。

直接MAIN出場にはしない。

SEED_EVENT免除＋seed assignment後の最終CompetitionRunはlegacyと完全一致。

## 次工程

Stage 13E-3D-2:

- qualification_rules
  - 49地方大会 winner → 夏甲子園
  - 秋地区/東京 winner → 神宮
- regional_feeder_rules
  - 県大会順位 → 地区大会
  - playoff_candidate
  - regional playoff

をLiveSeasonDependencyRuntimeへ拡張する。
