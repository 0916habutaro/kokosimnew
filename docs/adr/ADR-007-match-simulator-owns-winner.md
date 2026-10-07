# ADR-007: 能力ベース試合シミュレータが勝敗を所有する

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 12の大会エンジンはトーナメント進行を完成させるため、Match.winner / loserを先に決定している。

Stage 13で選手能力を導入した後もwinnerを大会エンジン側で先に決めると、能力ベースで生成した得点と勝者が矛盾する可能性がある。

## Decision

能力ベース試合ではMatchSimulatorがscoreとwinner / loserを決定する。

その後、TournamentEngineのMatchへ結果を同期してからResultViewを生成する。

ResultViewは同期漏れを隠さず、scoreとwinnerが一致しなければエラーとする。

移行期間中はStage 12の `generated_v1` をfallbackとして残す。

score source優先順位は

1. override
2. ability_model_v1
3. generated_v1

とする。

## Consequences

- 能力差が勝敗へ直接反映できる
- 得点とトーナメント進行の二重真実を防げる
- 既存ResultViewは後方互換を維持できる
- Stage 13C-2ではTournamentEngine側の実行順変更が必要
