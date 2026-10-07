# ADR-017: MAIN bracketを組合せ骨格と勝敗解決へ分離する

- Status: Accepted
- Date: 2026-10-08

## Context

従来のrun_main_single_elimination()は、

1. bracket生成
2. match生成
3. MatchResolver呼び出し
4. winner決定
5. 次round生成
6. outcome確定

を1関数で一括実行していた。

この構造ではゲーム内日付に応じて「今日の試合だけ実行」できない。

## Decision

既存run_main_single_elimination()は後方互換のため維持する。

並行してMainTournamentRuntimeStateを導入し、

- bracket skeleton
- match readiness
- result resolution
- winner propagation
- outcome materialization

を別操作にする。

TournamentEngineにはprepare_main_runtime()を追加する。

## Compatibility rule

同じAnnualCompetitionInput・seed・resolverを使い、runtimeをresolve_all()した結果は legacy TournamentEngine.run() のCompetitionRun.to_dict()と完全一致しなければならない。

この互換性をrandom winner resolverとAbilityMainMatchResolverの両方で自動テストする。

## Consequences

### 利点

- future winnerが内部にも存在しない
- 当日に初めてMatchSimulatorを呼べる
- save/load対象となる途中bracket stateを明示できる
- legacy一括実行を壊さず段階移行できる

### 制約

Stage 13E-2はMAINのみ。

pre-MAIN formatは従来一括実行のままであり、Stage 13E-3で同様のruntime化が必要。
