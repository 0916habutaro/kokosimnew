# Stage 13E-1 Season Runtime State

作成日: 2026-10-08

## 目的

これまでのSeasonOrchestratorは1年分の大会を一括実行し、完成したSeasonExecutionを返す。

ゲームとして必要なのは、

- 現在日付
- 今日の試合
- 未消化試合
- 消化済み試合
- 日付を進めた時の結果反映
- その時点までの学校戦績・個人成績

である。

Stage 13E-1では、この時間進行の正本となるruntime stateを導入する。

## 段階導入

現行TournamentEngineは大会単位の一括実行であり、途中ラウンドで停止・再開するAPIを持たない。

そのためStage 13E-1では、

```
SeasonExecution
→ build_season_browse_views()
→ prepared runtime plan
→ SeasonRuntimeState
```

という構成を採る。

prepared plan内部には現行エンジンが作った完成結果が存在するが、公開runtime stateでは未来結果を隠す。

Stage 13E-2でTournamentEngineをresume可能にした後、prepared resultを実際の当日simulationへ置換する。

## Match status

### pending

日付が決まっており、まだ消化されていない。

公開値:

- score = None
- winner / loser = empty
- score_source = empty

### completed

消化済み。

公開値:

- score
- winner / loser
- score_source
- result_text

ability試合ならMatchSimulationResult detailもcompleted ability resultとして利用可能。

### unscheduled

match_dateがない試合。

日付進行では自動消化しない。

Stage 12のcalendar research_pendingや、未確定game_date_listを安全に扱うための状態。

### bye

実試合ではないため初期状態からcompleted扱い。

ゲーム数・学校戦績には含めない。

## Runtime date

`SeasonRuntimeState.current_date`

を正本とする。

制約:

- season year内
- 後戻り禁止
- yearを跨いだnext_day禁止

default start:

`YYYY-01-01`

任意のstart_dateを指定した場合、その日より前のdated matchは既消化として初期反映する。

これにより途中日付からのresume相当fixtureを作れる。

## Operations

### today_matches()

現在日に予定された実試合を返す。

pendingなら未来結果を含まない。

### play_today()

現在日のpending試合だけcompletedへ移す。

同日に2回呼んでも2回目は0件。

### next_day()

1. play_today()
2. current_date + 1 day

### advance_to(target)

targetの直前日までを消化し、target日へ移動する。

target日の試合はまだpending。

### advance_through(target)

advance_to(target)後にtarget日も消化する。

## Result application

completedへ移った時点で初めて以下を公開する。

- score
- winner
- loser
- ability detail

`completed_ability_results()`

は消化済み能力試合だけを返す。

将来のability resultはpublic snapshotへ含めない。

## Dynamic school record

`school_records()`

はcompleted実試合だけから

- games
- wins
- losses
- runs_for
- runs_against
- run_differential

を再集計する。

したがって4/1時点で4/2決勝の勝敗は学校戦績へ入らない。

## Competition state

`competition_state()`

は

- completed count
- pending count
- unscheduled count
- complete flag
- champion

を返す。

championは全実試合completedになるまで空。

完了後はMAINの最終round winnerを採用する。

## Public snapshot

`public_snapshot()`

はUI / 将来のsave contract用の公開状態。

prepared future resultやability detailを含めない。

Stage 13G save/loadでは、runtime stateを保存する形式を別途決定する。

## 日程source

Stage 12 browse viewの日程割当をそのまま使用する。

- override
- projected_v1
- undated
- bye

projected_v1は公式match単位日程ではなく、game_date_list上の表示用割当である。

Stage 13Eで実ゲーム日程正本へ昇格させる場合は、match-level schedule生成方式を別revisionで導入する。
