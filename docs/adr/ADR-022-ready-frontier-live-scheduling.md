# ADR-022: live scheduleはready frontierだけを日付へ割り当てる

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3C

## Context

Stage 13E-3Bまででcompetition runtimeはlazyになったが、
ゲーム内current_dateとruntimeはまだ接続されていなかった。

全matchを先に日付へ投影すると、後続roundの対戦相手や
seed / qualifier結果に依存するstageを未来までmaterializeする必要がある。

また既存season_calendarにはMAIN日程を中心とした行があり、
pre-MAINの日付が未構造化の大会もある。

## Decision

日付schedulerは現在readyなfrontierだけをscheduleする。

- resolverはplay_date時だけ呼ぶ
- dependent waveは前wave完了後にactivateする
- byeで後roundが先行READYでもminimum round frontierを優先する
- stage固有日付はstage_date_listsで注入可能にする
- 日付不足時はcalendar_gapで停止する
- 架空日付は生成しない

Stage 13E-1のprepared SeasonRuntimeStateは互換用に残し、
live game progressionにはLiveSeasonRuntimeStateを追加する。

## Consequences

### Positive

- current_dateより未来の勝敗を内部にも生成しない
- future participant leakを防止できる
- pre-MAINからMAINまで同じ日付runtimeで進行可能
- 既存season_calendarを壊さず段階的にstage dateを精密化できる
- calendar不足をデータ品質gapとして検出できる
- legacy result compatibilityを維持できる

### Trade-offs

- exact stage datesがない大会はcalendar gapになる可能性がある
- ready wave単位の日付割当はmatch-by-match公式時刻の再現ではない
- full season dependencyは次工程でSeasonExecutor側と接続する必要がある

## Follow-up

Stage 13E-3Dでpre-MAIN stage calendarとcross-competition dependencyをlive season graphへ接続する。
