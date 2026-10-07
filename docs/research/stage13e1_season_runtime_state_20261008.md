# Stage 13E-1 Season Runtime State 実装報告

作成日: 2026-10-08

## 実装対象

新規:

- `phase2_engine/season_runtime.py`
- `tests/test_stage13e1_season_runtime_state.py`

package export:

- SeasonRuntimeState
- RuntimeMatchState
- RuntimeMatchResult
- MATCH_PENDING
- MATCH_COMPLETED
- MATCH_UNSCHEDULED

## Runtime model

### current_date

ゲーム内現在日。

### match status

- pending
- completed
- unscheduled

byeはcompletedとして初期化する。

### future result hiding

pending / unscheduledでは

- team1_score
- team2_score
- winner_id
- loser_id
- score_source
- result_text

を公開しない。

public_snapshotにもprepared resultを含めない。

## Date operations

- play_today
- next_day
- advance_to
- advance_through

後戻りとseason year越えは禁止。

## State projection

completed試合だけからschool_recordsを動的再計算。

competition_stateは大会完了までchampionを公開しない。

completed_ability_resultsは消化済み能力試合のみ。

## Fixture

実DataRepositoryからdirect MAIN大会と4校を動的選択。

AbilityMatchResolverで3試合を生成し、calendar fixtureを

- 2026-04-01
- 2026-04-02

の2日へ設定。

browse projectionにより

- 4/1 準決勝2試合
- 4/2 決勝1試合

として検証する。

3校fixtureではbyeの初期completedも確認する。

## Stage 13E-1の位置づけ

TournamentEngine自体はまだ一括実行。

したがって内部prepared planには未来結果がある。

ただしruntime公開state・学校戦績・ability resultsへの反映は日付消化まで遅延される。

Stage 13E-2でTournamentEngineのlazy/resume実行へ進む。
