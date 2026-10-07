# ADR-019: 後続phaseは前phase完了後に初めて生成する

- Status: Accepted
- Date: 2026-10-08

## Context

FMT006ではPOOL_RRの順位が確定しないとCROSS_PLAYOFF参加校を決められない。

prepare時点でpool結果を先に生成してCROSS_PLAYOFFを組むと、Stage 13Eの「未来結果を内部にも持たない」という原則に反する。

## Decision

dependencyを持つ後続phaseは、必要な上流phaseがcompleteになった時点で初めて生成する。

FMT006では:

1. prepare: POOL_RR matchだけ生成
2. pool完了: standings/ranking確定
3. CROSS_PLAYOFF match生成
4. cross playoff完了: qualifier outputs確定
5. 全group完了: MAIN runtime生成

とする。

## Compatibility

lazy化によって既存のmatch_id、RNG namespace、pool ranking、standings、match metadata、group output orderを変更しない。

resolve_all()したCompetitionRunはlegacy一括runと完全一致しなければならない。

## Consequences

このphase activation方式をStage 13E-3B-2の

- PRIMARY→REPECHAGE
- PRIMARY→SECONDARY
- POOL/ZONE→決定戦

へそのまま拡張できる。
