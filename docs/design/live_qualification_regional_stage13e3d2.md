# Stage 13E-3D-2 qualification / regional live dependency

作成日: 2026-10-08

## 目的

Stage 13E-3D-1では、同年competition_access_rulesをlive dependencyへ接続した。

3D-2では大会間依存を以下へ拡張する。

- qualification_rules
  - 49地方大会優勝 → 夏全国大会
  - 秋地区大会・東京秋優勝 → 明治神宮大会
- regional_feeder_rules
  - 県大会順位 → 地区大会
  - 推薦枠との重複除外
  - rank_range / fill_to_quota
  - playoff_candidate
- regional_qualification_playoffs
  - 近畿2組の出場決定戦

source大会の結果解禁日についてはADR-023を継承し、
公式game_date_list最終日までdestinationをactivateしない。

## rule inventory

2026:

- qualification_rules: 59
  - QRL000001〜049: 夏地方大会winner → CMP000002
  - QRL000050〜059: 秋地区大会/東京winner → CMP000003
- regional_feeder_rules: 96
  - 春地区大会: RFR000001〜047
  - 秋地区大会: RFR000048〜096
- regional_qualification_playoffs: 2
  - KPL2026A
  - KPL2026B

## dependency family

LiveSeasonDependencyRuntimeStateはdestinationごとにdependency familyを判定する。

- access
- qualification
- regional_feeder
- root

現行2026 graphでは1 destinationにつき1 family。

複数familyが同時にdestinationへ設定された場合は、
暗黙にmergeせずblockedとして扱う。

これは将来複合依存を追加する際の設計境界とする。

## qualification_rules

### selector

3D-2では source_result=winner を機械解決する。

source ScheduledCompetitionRuntimeがcompleteし、
さらに公式result release dateへ到達した後、

CompetitionRun.outcome.champion_school_id

を1校取得する。

quotaとの一致を確認し、
全ruleがPASSした時だけdestination runtimeを生成する。

### 夏全国大会

CMP000023〜CMP000071の49地方大会から各winnerを1校取得。

QRL順にdeduplicateし49代表を構成する。

CMP000002 team_count=49と一致した時だけactivate。

### 明治神宮大会

CMP000013〜CMP000022の10地区代表大会からwinnerを取得。

CMP000003 team_count=10と一致した時だけactivate。

2026-10-08時点のCMP000003 season_calendarは開催期間のみで
game_date_listが未確定。

そのためqualifier 10校の確定までは可能だが、
試合日が入るまではScheduledCompetitionRuntimeはcalendar gapとして保持する。

未来日程を推測して生成しない。

## regional_feeder_rules

legacy SeasonOrchestrator._resolve_regional_feeders()と同じ契約をlive化する。

### rank_range

source CompetitionRun.outcome.final_ranking_school_idsを使用。

rank_from / rank_toでsliceする。

### exclude_already_selected

既にdestinationへ選出済みの学校を除外する。

### fill_to_quota

rank_toでscanを止めず、
下位順位まで走査してquotaを満たす。

2026春九州の選抜推薦との重複補充で使用する。

### national_invitational_participants

source_type=national_invitational_participants
selector=participants_from_region

では、完了したCMP000001のentrant_school_idsを
prefecture_region_membershipsのregionでfilterする。

既存SeasonExecutorのsenbatsu participant set相当を
live source CompetitionRunから取得する。

## regional playoff

qualification_mode=playoff_candidateでは
feeder ruleの1校をcandidate poolへ保存する。

regional_qualification_playoffs.csvに従い2校を対戦させる。

勝者決定はlegacyと同じ

shuffled(
  [a, b],
  season_rng_seed,
  "regional_playoff:{playoff_id}:{a}:{b}"
)[0]

を使う。

これによりKPL2026A / KPL2026Bの構造結果がlegacyと一致する。

現時点ではregional playoffは独立MatchResolver試合ではなく、
Stage12Eから継承したdeterministic structural playoff。

公式年間対戦結果を入力する仕組みは将来差し替え可能。

## activation contract

destinationのactivate条件:

1. dependency family内の全sourceがlive graphに存在
2. 全source runtimeがcomplete
3. current_date >= 各sourceの公式result release date
4. 全rule resolutionがPASS
5. destination entrant countがcompetition.team_countと一致
6. destination初回schedule date > dependency activation date

条件不足時はdestination runtimeをmaterializeしない。

## 実データ validation

### 夏全国

49地方大会CMP000023〜071を実calendarでlive進行。

最後の地方大会公式最終日までCMP000002は存在しない。

49 rule PASS後に49代表でactivate。

CMP000002を8/22まで進行し、
同じ49 entrants / rng_seedのlegacy TournamentEngine.run()と
CompetitionRun.to_dict()完全一致。

### 春季四国

source:

- CMP000139 徳島
- CMP000141 香川
- CMP000143 愛媛
- CMP000145 高知

各final_ranking上位2校を選出し8校でCMP000011をactivate。

SeasonOrchestrator._resolve_regional_feeders()のentrant順と完全一致。

CMP000011完了後CompetitionRunもlegacyと完全一致。

### 近畿秋playoff

CMP000118 / 120 / 122 / 124 / 126 / 128の
synthetic completed rankingをlegacy resolverとlive resolverへ同時入力。

- feeder resolved_school_ids
- KPL2026A winner
- KPL2026B winner
- 16 entrants order

すべて一致。

### 神宮

CMP000013〜022のcompleted winnerをQRL000050〜059へ入力し、
10代表のannual templateを構築できることを確認。

## 次工程

Stage 13E-3D-3候補:

- full-season dependency graph builder
  - annual template自動生成
  - source/destination topological planning
  - waiting_externalの一覧化
- 2026 pre-MAIN stage calendar 49件のverified化
- regional playoffをMatchResolver対応の正式runtimeへ昇格

3D-2時点で既存SeasonExecutorの主要な同年大会間進出規則はlive graphへ移植完了。
