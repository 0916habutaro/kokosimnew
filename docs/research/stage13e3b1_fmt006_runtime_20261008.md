# Stage 13E-3B-1 FMT006 runtime 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/premain_runtime_fmt006.py
- tests/test_stage13e3b1_fmt006_runtime.py

更新:

- phase2_engine/premain_competition_runtime.py
- phase2_engine/engine.py
- phase2_engine/__init__.py
- Stage 13E-3A scope guard

## 実大会fixture

神奈川春 CMP000095。

既存 _kanagawa_demo() を使用し、

- qualifier entrants: 162校
- direct MAIN: 1校
- qualifier outputs: 81校
- MAIN entrants: 82校

の既存contractを維持する。

## Lazy phase boundary

prepare直後:

- resolver call 0
- POOL_RRだけready
- CROSS_PLAYOFF未生成
- MAIN未生成

pool phase完了後:

- pool standings/ranking確定
- CROSS_PLAYOFF生成
- MAINはまだ未生成

cross playoff完了後:

- qualifier output確定
- MAIN runtime生成

## Legacy equivalence

確認経路:

1. random winner
2. detailed MatchResolution stub
3. annual group_pool_assignments override

全経路でCompetitionRun.to_dict()完全一致。

detailed resolverではresolver call sequenceとmatch_simulation_results keyも一致。

## GitHub Actions

- Stage 13E-3B-1専用テスト: 5件
- full suite: Ran 506 tests in 16.599s
- OK

## 補足

初回CIでは全加盟校を直接fixtureへ入れたため、既存FMT006 demo contractの対象校数と不一致になった。

既存 _kanagawa_demo() を再利用し、実装ではなくfixtureを修正した。

## 次工程

Stage 13E-3B-2:

FMT002〜005 / 007〜025の複合phaseを共通runtime primitiveのcompositionとして接続する。
