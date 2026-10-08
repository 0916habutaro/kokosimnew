# Stage 13E-3D-3 full-season live graph planner

作成日: 2026-10-08

## 目的

Stage 13E-3D-2までで、同年大会間依存を

- competition_access_rules
- qualification_rules
- regional_feeder_rules
- regional_qualification_playoffs

までLiveSeasonDependencyRuntimeStateへ接続した。

ただしruntime生成時には、呼び出し側が対象大会ごとのAnnualCompetitionInputを
すべて手作業で渡す必要があった。

Stage 13E-3D-3では、2026大会マスター・依存ルール・日程から
年間162大会のannual templateとdependency graphを自動生成する。

## 新規クラス

### LiveSeasonGraphPlanner

入力:

- DataRepository
- data root
- season rng seed
- year

出力:

- LiveSeasonGraphPlan

### LiveSeasonGraphPlan

保持:

- 162大会のLiveSeasonPlanEntry
- 162 AnnualCompetitionInput templates
- annual build strategy
- season_calendar rows
- competition_stage_calendar rows
- dependency edge
- topological order
- external access bootstrap resolutions
- warning

build_runtime()から
LiveSeasonDependencyRuntimeStateを直接生成できる。

## annual template strategy

2026全162大会を以下へ分類する。

### senbatsu_bootstrap: 1

CMP000001。

既存SeasonOrchestratorの2026 structural Senbatsu bootstrapを再利用し、
32校のAnnualCompetitionInputを作成する。

これは前年秋の選考結果をcurrent-year competition graphだけでは生成できないため。

### summer_area: 49

CMP000023〜CMP000071。

competition.qualifying_area_idとarea membershipから
49地方大会のentrantを自動生成する。

### structural: 81

県単位構造をStructuralAnnualInputFactory.build_prefectural()で生成する。

前年秋成績や新人戦など、current-year competitionとしてmaterializeされていない
access sourceは先にstructural bootstrapし、そのdirect entryを入れて構築する。

### deferred_structural: 13

同年competition_access_rulesの結果が必要な大会。

例:

- CMP000004 北海道春
- CMP000016 東京秋
- CMP000077 宮城秋
- CMP000095 神奈川春
- CMP000116 三重秋
- CMP000144 愛媛秋

planner時点ではfuture result-derived school idを入れない。

templateはentrant_school_ids=[]のまま保持し、
source結果確定後にLiveSeasonDependencyRuntimeStateが
StructuralAnnualInputFactory.build_prefectural()を呼び直す。

### dependency_aggregate: 18

全entrantがqualification/regional feederで決まる大会。

- CMP000002 夏全国
- CMP000003 神宮
- 春地区大会8大会
- 秋地区大会8大会

templateは空entrantで作成し、
dependency fan-in完了時にentrantを確定する。

## external access bootstrap

competition_access_rules 22件のうち、
current-year source competitionで解決できない8件を
既存SeasonOrchestratorと同じstructural bootstrapで解決する。

内訳:

- 前年秋県大会: 6件
- 前年秋地区大会: 1件
- 当年新人戦（独立competition未materialize）: 1件

使用例:

- 東京春 CMP000094: 前年秋本大会64校
- 沖縄秋 CMP000128: 新人戦ベスト4 proxy

future current-year resultのplaceholderには使用しない。

全8件は2026 masterでPASS。

## deferred structural builder

LiveSeasonDependencyRuntimeStateへ

- annual_build_strategies
- structural_factory

を追加。

access rule解決後、
strategy=deferred_structuralなら、
prebuilt templateへ学校IDを直接足すのではなく、
resolved direct/bypassを引数にStructuralAnnualInputFactoryを再実行する。

この方式が必要な代表例が東京秋CMP000016。

CMP000016は東西東京夏優勝2校が分からないと

- preliminary対象230校
- direct 2校
- total 232校

のpartitionを正しく構築できない。

planner段階では2校を仮置きせず、
source確定後に初めて232校構造を作る。

## dependency graph

same-year edge:

- access: 14 rule / 13 destination
- qualification: 59 rule / 2 destination
- regional feeder: 96 rule / 16 destination

source→destinationの重複edgeを除去すると165 edge。

Kahn topological sortを使用する。

ready nodeのtie-breakは

1. season_calendar.start_date
2. competition_id

とする。

2026はcycle 0。

topological orderは162大会すべてを1回ずつ含む。

## full-season startup

plan.build_runtime(start_date="2026-01-01")

で162 templateを一括投入する。

初期状態:

- root active: 131
- waiting_dependencies: 31

未来のdependency destinationはruntime自体を生成しない。

## pre-MAIN calendar

competition_stage_calendar.csvをplannerが自動読込する。

現状:

- research_pending: 49
- verified: 0

そのためpre-MAIN日程未確認大会は、
full-season graphでもMAIN日程へ誤fallbackせずcalendar gapで停止する。

これはplannerが日付を推測しないための意図した挙動。

## full live validation

plannerだけで1/1から8/5まで進行。

確認:

### 夏全国

49地方大会をrootとして自動実行。

全49 winnerが公式result release dateへ到達した後、
CMP000002を49 entrantsでmaterialize。

手動AnnualCompetitionInput不要。

### 東京秋

CMP000036東東京・CMP000037西東京が完了するまで
CMP000016 runtimeは存在しない。

両winner解禁後にdeferred structural builderが起動。

結果:

- direct_main_entry_school_ids: 2
- entrant_school_ids: 232
- direct 2校はentrant setに含まれる
- PRELIMINARY_QUALIFIER日程はpendingのためcalendar gap

future school placeholderは0。

## 既存SeasonOrchestratorとの関係

plannerの外部bootstrapは、互換性維持のため
SeasonOrchestratorのstructural bootstrapをoracleとして再利用する。

Live runtimeの最終目標はSeasonOrchestratorを置換することだが、
既存の前年コンテキスト生成ロジックを同時に再実装して差分を増やさない。

将来bootstrap contextを独立serviceへ抽出可能。

## 次工程

Stage 13E-3E候補:

1. pre-MAIN 49 stageの日付research_pending→verified
2. full-season save/load
3. game startup facade
   - new season
   - resume season
   - current_date
4. planner/runtimeのread model統合
5. 正式GUIが読むseason service contract固定

3D系列としては、
単一大会lazy化から年間dependency graph自動構築まで到達した。
