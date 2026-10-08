# Stage 13E-3C live season schedule runtime

作成日: 2026-10-08

## 目的

Stage 13E-3B-3までで、都道府県大会の主要pre-MAIN graphをMatchResolver未実行のままprepareし、試合単位でincrementalに進行できるようになった。

Stage 13E-3Cでは、このcompetition runtimeをゲーム内日付へ接続する。

目標:

- current_date以前の試合だけ結果を持つ
- current_date当日のready matchだけ実行する
- 前段stageの結果が出るまで後続stageの日付・対戦相手を生成しない
- 日付データが不足する場合は架空日付を生成せずgapとして停止する
- 日付進行後もlegacy TournamentEngine.run()との最終結果互換を維持する

## 新規runtime

### ScheduledCompetitionRuntime

任意のStage 13E competition runtimeを日付へ接続するadapter。

入力:

- competition runtime
- season_calendar row
- optional stage_date_lists

状態:

- activated matches
- pending / completed
- processed_dates
- last_scheduled_date
- calendar_gap_match_ids

### LiveSeasonRuntimeState

Stage 13E-1 SeasonRuntimeStateのlive execution版。

Stage 13E-1は完成済みSeasonExecutionから未来結果をhiddenにしていた。

LiveSeasonRuntimeStateは完成済みCompetitionRunを保持せず、

AnnualCompetitionInput
→ TournamentEngine.prepare_competition_runtime()
→ ScheduledCompetitionRuntime
→ current_date

の順で実行する。

## 日付割当

### ready waveだけを割り当てる

scheduler生成時にruntime.ready_matches()を取得する。

その時点でreadyな最前線だけを、利用可能な最初の日付へ割り当てる。

試合結果は生成しない。

play_date()で当日分を解決した後に初めて次waveをscheduleする。

したがって、

- future winner
- future score
- future dependent participant
- future MAIN entrant

は前段完了前には公開stateへ存在しない。

### round frontier

MAIN bracketはbye propagationにより、round1未完了でも一部round2がREADYになる場合がある。

legacy MainTournamentRuntimeState.resolve_ready_round()はminimum roundから処理する。

ScheduledCompetitionRuntimeも

stage_code
+ phase_code
+ group_id

ごとのminimum roundだけをcurrent frontierとしてscheduleする。

これによりresolver call orderとCompetitionOutcomeの同順位cohort順をlegacyと一致させる。

## calendar source

### competition-wide dates

season_calendar.csv の game_date_listを利用できる。

この場合date_sourceは runtime_wave_v1。

### stage-specific dates

pre-MAINの正確な日付が別途判明している場合は

stage_date_lists = {
  "BRANCH_QUALIFIER": [...],
  "SEED_EVENT": [...],
  "FIRST_TOURNAMENT": [...],
}

のようにstage_code単位で入力できる。

stage-specific dateのdate_sourceは stage_date_list。

### 日付不足

利用可能日がなく、runtimeにREADY matchが残る場合:

- match_date=""
- date_source="calendar_gap"
- resolver未実行
- competition未完了

とする。

不足分をMAIN日程へ自動的に押し込むことや、架空日付の生成は行わない。

## LiveSeason date operations

- today_matches()
- matches_for_date()
- play_today()
- next_day()
- advance_to()
- advance_through()

Stage 13E-1と同じ意味を維持する。

next_day()は現在日を処理して翌日へ移動する。
target dateそのものを処理するのはadvance_through()。

## midseason start

start_date以前にschedule済みのlive matchだけをresolverで解決する。

start_date当日以降は未実行のまま保持する。

これによりロード開始時点までの履歴を再現しつつ、当日以降の結果は生成しない。

## result projection

completed matchだけから

- completed_results
- completed_ability_results
- school_records
- champion / runner-up

を公開する。

championはcompetition runtime完了前には空文字。

## compatibility validation

### MAIN-only

8校・3roundを3日へ割当。

日付進行後のCompetitionRun.to_dict()がlegacyと完全一致。

### 北海道春 CMP000004

BRANCH_QUALIFIERの日付をstage_date_listsとして与え、
MAINはcompetition calendar datesを利用。

BRANCH_QUALIFIER
→ MAIN

を日付進行し、最終CompetitionRunがlegacyと完全一致。

### 岐阜秋 CMP000110

SEED_EVENT
→ FIRST_TOURNAMENT
→ MAIN

をstage date付きで進行。

byeにより先行READYとなるMAIN roundをfrontier制限し、
最終CompetitionOutcomeまでlegacyと完全一致。

## 既存SeasonRuntimeStateとの関係

SeasonRuntimeState.from_prepared_season()は既存GUI/read model互換のため残す。

新規ゲーム進行はLiveSeasonRuntimeStateを使用する。

将来save/load contractを固定する際に両者の公開viewを統合する。

## 次工程

Stage 13E-3Dでは、2026実データのpre-MAIN stage dateを構造化し、
LiveSeasonRuntimeStateをSeasonExecutorのcompetition dependencyへ接続する。

特に、

- 支部予選
- seed event
- FIRST_TOURNAMENT
- prefectural preliminary
- source competition完了待ち

を実calendar dependencyとして扱う。
