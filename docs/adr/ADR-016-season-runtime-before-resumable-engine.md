# ADR-016: 日付進行stateをTournamentEngineのresume化より先に固定する

- Status: Accepted
- Date: 2026-10-08

## Context

現行TournamentEngineは1大会を一括完走する。

ゲーム本体では1日ずつ進み、その日に行われる試合だけが確定する必要がある。

TournamentEngineを先に全面的にresume可能へ変更すると、

- 全format model
- pre-MAIN
- MAIN
- qualification
- regional bridge
- SeasonOrchestrator

を同時に変更する必要があり、回帰範囲が大きい。

## Decision

Stage 13E-1では時間進行の外部contractを先に固定する。

完成済みSeasonExecutionをprepared planとして使うが、

- pending future scoreは非公開
- pending future winnerは非公開
- pending future ability detailは非公開

とする。

`play_today()` で当日分だけcompletedへ移す。

Stage 13E-2では同じSeasonRuntimeState APIを維持しながら、prepared result適用を実際のlazy MatchResolver呼び出しへ差し替える。

## Consequences

### 利点

- UI・save/load・日付進行が依存するcontractを早期に固定できる
- 大会エンジン全面改修と状態管理を分離できる
- future result leakageを自動テストできる
- undated calendarを明示状態として扱える

### 制約

- Stage 13E-1内部では未来結果がprepared planに存在する
- late roundのparticipantもprepared run由来
- 真の「当日に初めて勝敗生成」はStage 13E-2で実装する

この制約は外部公開stateには露出させない。
