# ADR-008: 個人成績は試合イベントと整合するcountを正本とする

- Status: Accepted
- Date: 2026-10-07

## Context

ゲームでは打率・OPS・防御率など多くの表示値が必要になる。

これらを試合生成時に個別保存すると、イベント・得点・個人成績・率指標の間で不整合が起きやすい。

## Decision

試合単位ではMatchEventと整数countのGameStatsを正本とする。

率指標は保存せずread modelで導出する。

MatchSimulationResult validatorで少なくとも以下を相互検算する。

- scoreとteam runs
- event runsとscore
- batter runsとteam runs
- batter hitsとteam hits
- opponent pitcher runs allowedとteam runs
- opponent pitcher hits allowedとteam hits
- batter PAとopponent pitcher BF

投球回はouts_recordedで保存する。

## Consequences

- 表示率を後から定義変更できる
- 集計バグを早期に検出できる
- Season/Career集約が単純なcount加算になる
- Stage 13C-2のイベント生成は必ずstats reconciliationを通す必要がある
