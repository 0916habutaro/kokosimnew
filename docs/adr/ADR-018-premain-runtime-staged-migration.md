# ADR-018: pre-MAIN runtime化をprimitiveとcompetition graphへ分離する

- Status: Accepted
- Date: 2026-10-08

## Context

pre-MAINには26 format modelがあり、単淘汰、block代表、round robin、gate、repechage、secondary phase、seed eventが組み合わされる。

各formatごとに独自runtimeを実装すると、試合解決・status・result sinkの重複が増える。

## Decision

まず競技要素を共通runtime primitiveへ分解する。

- SingleEliminationRuntimeState
- SingleRoundGateRuntimeState
- RoundRobinRuntimeState
- BlockForestRuntimeState

competition固有runtimeはこれらを合成する。

Stage 13E-3AではFMT001 qualifier→MAINを最初のcompositionとして実装する。

## Compatibility rule

primitiveは対応する既存brackets.py関数と

- ranking / winners
- Match dataclass列
- metadata
- detailed result sink

が完全一致しなければならない。

competition runtimeはlegacy CompetitionRun.to_dict()と完全一致しなければならない。

## Consequences

共通primitiveを先に固定することで、Stage 13E-3Bではformat modelごとの差分をphase compositionへ限定できる。

一方、3A終了時点ではFMT006や複合repechageを含むcompetition graphはまだ従来一括実行のまま残る。
