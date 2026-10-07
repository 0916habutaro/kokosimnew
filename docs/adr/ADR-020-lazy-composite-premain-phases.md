# ADR-020: pre-MAIN複合phaseをlazy compositionとして実行する

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3B-2

## Context

Stage 12Cでは都道府県ごとの複雑な予選方式を一括実行することで、全26 format modelの機械実行を実現した。

Stage 13Eではゲーム内日付に合わせて試合を1試合ずつ進める必要があり、大会開始時に未来の勝者や敗者復活出場校を確定してはならない。

複合方式では後続phaseのentrantが前phaseの結果に依存するため、全phaseをprepare時点で生成する方法は未来情報を内部に保持してしまう。

## Decision

複合qualifierをphase state machineとして構成し、後続phaseは依存元phaseが完了した時点で初めて生成する。

既存一括実行は削除せず、互換性検証のoracleとして残す。

runtimeは既存pre-MAIN primitiveを再利用し、RNG namespace、match_id、metadata contractをlegacyと一致させる。

competition-global方式FMT005はgroup runtimeへ無理に落とさず、専用global runtimeとして扱う。

## Consequences

### Positive

- 未来の敗者復活出場校・secondary出場校を大会開始時に生成しない。
- game date runtimeから試合単位で進行可能になる。
- Stage 12Cの結果互換性を自動検証できる。
- mixed-model stageも同じcompetition runtimeで扱える。
- formatごとの特殊ロジックをphase境界へ局所化できる。

### Trade-offs

- legacy一括実行とlazy runtimeの2経路を当面維持する。
- 複合formatのstate machineが増える。
- exact annual drawを将来導入する際はphase activation時にannual overrideを適用する必要がある。

## Follow-up

Stage 13E-3B-3でSEED_EVENTとFIRST_TOURNAMENTをlazy化し、pre-MAIN graph全体を同じ原則へ統合する。
