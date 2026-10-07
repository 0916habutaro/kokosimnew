# Stage 13E-3B-2 複合qualifier runtime 実装報告

作成日: 2026-10-08

## 実装

新規:

- `phase2_engine/premain_runtime_composite.py`
- `tests/test_stage13e3b2_composite_runtime.py`
- `docs/design/premain_runtime_composite_stage13e3b2.md`
- `docs/adr/ADR-020-lazy-composite-premain-phases.md`

更新:

- `phase2_engine/premain_competition_runtime.py`
- `phase2_engine/engine.py`
- `phase2_engine/__init__.py`
- `tests/test_stage13e3a_premain_runtime.py`
- `README.md`

## 対象format

qualifier:

- FMT002: PRIMARY + REPECHAGE
- FMT003: PRIMARY + SECONDARY
- FMT004: PRIMARY_TOP4 + SECONDARY
- FMT005: PRIMARY_GLOBAL + REPECHAGE_GLOBAL
- FMT007: MAIN_KO ranking
- FMT008: MAIN_KO + REP_DECIDERS
- FMT010: PRIMARY_BLOCKS + SECONDARY
- FMT011: PRIMARY_LEAGUE + SECONDARY
- FMT012: PRIMARY_ZONES + SECONDARY
- FMT013: PRIMARY_LEAGUE + SECONDARY
- FMT014: PRIMARY + SECONDARY
- FMT015: PRIMARY + PRIMARY_REPECHAGE + SECONDARY
- FMT016: PRIMARY + SECONDARY
- FMT017: ZONE_RR + placement playoffs
- FMT025: PRIMARY + REPECHAGE + RANKING

FMT001はStage 13E-3A、FMT006はStage 13E-3B-1で対応済み。

SEED_EVENT系FMT009 / FMT018〜024およびFIRST_TOURNAMENT FMT026はStage 13E-3B-3へ残す。

## Lazy phase boundary

後続phaseはprepare時に作成しない。

代表例FMT002:

1. prepare: PRIMARYだけ存在
2. PRIMARY完了: qualifier direct cohort確定
3. その時点でREPECHAGE entrant確定・bracket生成
4. REPECHAGE完了: group output確定
5. 全group output確定後にMAIN activate

FMT005も同じ原則で、PRIMARY_GLOBAL完了後に初めて全県REPECHAGE_GLOBALを生成する。

FMT015ではPRIMARY→PRIMARY_REPECHAGE→SECONDARYの各境界を順番にactivateする。

## mixed-model stage

CMP000113 / CMP000114のように、同一stage内でgroupごとにFMT010〜015が混在する大会も対応した。

各groupは独立runtimeとして進行し、すべてのgroupがcompleteになるまでMAINは生成しない。

## Legacy equivalence

以下20大会を対象に、同じannual input / RNG seedで

- legacy `TournamentEngine.run()`
- lazy `prepare_qualifier_main_runtime().resolve_all()`

の `CompetitionRun.to_dict()` 完全一致を確認した。

- CMP000074
- CMP000075
- CMP000076
- CMP000077
- CMP000082
- CMP000083
- CMP000085
- CMP000093
- CMP000107
- CMP000108
- CMP000109
- CMP000111
- CMP000112
- CMP000113
- CMP000114
- CMP000115
- CMP000124
- CMP000134
- CMP000135
- CMP000136

これにより、対象formatについて

- qualifier output
- phase code
- match ID
- bracket partition
- ranking
- metadata
- MAIN entrants
- MAIN bracket
- champion/outcome

の互換を確認した。

CMP000114ではdetailed MatchResolution stubでも完全一致し、resolver call sequenceと `match_simulation_results` keyも一致した。

## CI

最初のCIでは、Stage 13E-3Aに残っていた「FMT002は未対応であること」を要求する旧scope guardが1件失敗した。

B2でFMT002が正式対応になったため、scope guardを「SEED_EVENT graphはStage 13E-3B-3対象」に更新した。

修正後:

- Stage 13E-3B-2専用テスト: 5件
- full suite: `Ran 511 tests in 24.188s`
- `OK`

## 設計上の意味

Stage 13E-3B-2完了時点で、qualifier→MAIN graphはFMT001〜008、FMT010〜017、FMT025について大会開始時に未来結果を生成せず段階進行できる。

残る大きなpre-MAIN graphはseed event / first tournament系である。

## 次工程

Stage 13E-3B-3:

- SEED_EVENT
- FIRST_TOURNAMENT / FMT026
- seed event→qualifier→MAIN
- seed event→FIRST_TOURNAMENT→MAIN
- seed-only event→MAIN

をlazy runtimeへ接続する。
