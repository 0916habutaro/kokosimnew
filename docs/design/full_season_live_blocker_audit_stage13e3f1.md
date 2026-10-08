# Stage 13E-3F-1 2026 full-season live blocker audit

作成日: 2026-10-08

## 目的

Stage 13E-3Eまでで、

- 2026全162大会のlive graph
- lazy match resolution
- same-year dependency
- save/load
- save slot / autosave / recovery

まで実装した。

Stage 13E-3F-1では現行masterを変更せずに2026-01-01から2026-12-31まで
full-season live runtimeを実行し、年間完走を妨げるblockerを機械分類する。

仮の日付やfuture resultを注入しない。

## audit runner

新規:

- `phase2_engine/full_season_live_audit.py`
- `phase2_engine/full_season_live_audit_cli.py`

CLI:

```bash
python -m phase2_engine.full_season_live_audit_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100827 \
  --output-dir out/full_season_live_audit
```

出力:

- `competition_blockers.csv`
- `stage_calendar_priorities.csv`
- `blocker_actions.csv`
- `summary.json`

## year-end result

seed:

`2026100827`

2026-12-31まで処理。

### competition

total:

162

complete:

98

blocked / incomplete:

64

内訳:

- calendar_gap: 46
- waiting_dependency: 16
- blocked: 2
- incomplete_active: 0

completed match:

6176

## blocker origin

calendar_gap 46件をそのまま「日付不足」とは扱わない。

原因を分離した。

### pending_pre_main_calendar: 45 competitions

competition_stage_calendar.csvでresearch_pendingのpre-MAIN stageを持ち、
runtimeが実際にそのstageへ到達してcalendar gapになった大会。

### calendar_gap_without_pending_stage: 1 competition

CMP000079 秋田秋。

pre-MAIN research_pending rowがないのにcalendar gapが1試合残る。

既存season_calendarの注記は

- 8/27〜9/7「秋季県大会予選」を本大会match_datesから除外

としている一方、
competition_stages.csvはCMP000079にMAINしか持たない。

したがって単純なMAIN game_date不足ではなく、
前段予選がstageとして未構造化の可能性を優先確認する。

### dependency_resolution_failure: 2 competitions

- CMP000095 神奈川春
- CMP000113 愛知春

いずれもresearch_pending pre-MAIN stageを持つが、
そのstageへ到達する前にdependency resolutionでblocked。

対象:

- ACR000008
- ACR000012

source:

CMP000001 センバツ

selector:

participant_from_destination_prefecture

observed/expected count:

1

structural Senbatsu bootstrapで対象都県participant数が期待値と一致せず、
LiveAccessDependencyResolution=FAILとなる。

したがってこの2大会はpre-MAIN日付を埋めるだけでは進行しない。

### upstream_dependency: 16 competitions

直接blockerではなく、上流大会が完了しないため未materialize。

内訳:

春地区:

- CMP000005 東北
- CMP000006 関東
- CMP000007 北信越
- CMP000008 東海
- CMP000009 近畿
- CMP000010 中国
- CMP000012 九州

秋地区:

- CMP000014 東北
- CMP000015 関東
- CMP000017 北信越
- CMP000018 東海
- CMP000019 近畿
- CMP000020 中国
- CMP000021 四国
- CMP000022 九州

全国秋:

- CMP000003 明治神宮

合計16。

## spring regional result

春地区大会9大会のうち:

- CMP000004 北海道: 自身のpre-MAIN日付不足でcalendar gap
- CMP000005/006/007/008/009/010/012: prefectural source待ち
- CMP000011 四国: 完了

四国春は4県のsourceが全て現行masterで完走できるため、
地区大会まで完了できる。

## national result

### CMP000001 センバツ

complete。

### CMP000002 夏甲子園

complete。

49地方大会→49代表→全国大会のdependency chainは
現行masterで年間live進行可能。

### CMP000003 明治神宮

waiting_dependency。

必要な秋10代表:

- CMP000013 北海道: calendar gap
- CMP000014 東北: upstream wait
- CMP000015 関東: upstream wait
- CMP000016 東京: calendar gap
- CMP000017 北信越: upstream wait
- CMP000018 東海: upstream wait
- CMP000019 近畿: upstream wait
- CMP000020 中国: upstream wait
- CMP000021 四国: upstream wait
- CMP000022 九州: upstream wait

10 source全て未完了のためactivateしない。

## pre-MAIN stage master

research_pending row:

49

competition:

47

runtimeでstageへ到達:

47 rows

到達前にdependency blocked:

2 rows

- CMP000095 / STG000177
- CMP000113 / STG000184

### stage priority

dependency impactで3 tier。

#### P0_national_chain: 28 rows

すべて秋。

解消しないと秋地区大会または直接Jingu代表が確定せず、
最終的にCMP000003を止める。

#### P1_regional_chain: 20 rows

春県大会。

解消しないと春地区大会を止めるが、
同年全国大会dependencyには波及しない。

#### P2_local_only: 1 row

CMP000004 北海道春。

同年後続dependencyなし。

## additional action queue

stage date 49件だけでは不足するため、
blocker_actions.csvを作る。

action total:

52

type:

- verify_pre_main_stage_dates: 49
- review_unmodeled_pre_main_structure: 1
- fix_dependency_resolution: 2

priority:

- P0: 29
- P1: 22
- P2: 1

### P0追加1件

`structure:CMP000079`

秋田秋の前段予選構造を確認。

Jingu chainへ波及するためP0。

### P1追加2件

- `dependency:CMP000095`
- `dependency:CMP000113`

Senbatsu structural bootstrapとaccess ruleの整合を修正。

両大会のpre-MAIN stage日付調査より先に直す必要がある。

## prioritization rule

stageの日付調査量や参加校数ではなく、
downstream dependency impactを優先する。

1. P0: national chainを止める
2. P1: regional chainを止める
3. P2: 同年dependencyなし

同tier内では、

- dependency resolution / structure defect
- stage date research

の順。

日付を調べてもruntimeへ到達できないblockerを先に直す。

## automated regression

専用7 tests。

確認:

- year-end exact counts
- waiting dependency exact set
- stage reachability
- CMP000079 special gap
- CMP000095 / CMP000113 resolution failures
- priority tiers
- national completion state
- CSV / JSON output rows

full suite:

`Ran 568 tests in 53.286s`

`OK`

## next

Stage 13E-3F-2はP0 remediationを優先する。

候補順:

1. CMP000079 秋田秋の前段予選構造確認・stage化
2. P0 autumn pre-MAIN 28 rowsの実日付verified化
3. full-season audit再実行
4. Jingu chainがどこまで解消したか確認

P1のCMP000095 / CMP000113 dependency resolution修正と
春pre-MAIN 20 rowsはP0完了後でもよい。
