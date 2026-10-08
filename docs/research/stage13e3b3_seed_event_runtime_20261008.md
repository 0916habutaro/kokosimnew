# Stage 13E-3B-3 SEED_EVENT / FMT026 runtime 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/premain_runtime_seed_event.py
- phase2_engine/premain_graph_runtime.py
- tests/test_stage13e3b3_seed_event_runtime.py
- docs/design/premain_runtime_seed_event_stage13e3b3.md
- docs/adr/ADR-021-lazy-seed-event-stage-activation.md

更新:

- phase2_engine/premain_runtime_forest.py
- phase2_engine/premain_competition_runtime.py
- phase2_engine/engine.py
- phase2_engine/__init__.py

## 対象大会

seed graphを持つ9大会を回帰対象とした。

- 青森春 CMP000072
- 青森秋 CMP000073
- 岐阜秋 CMP000110
- 三重秋 CMP000116
- 徳島秋 CMP000140
- 愛媛秋 CMP000144
- 宮崎秋 CMP000158
- 鹿児島秋 CMP000160
- 沖縄秋 CMP000162

## 対応graph

### SEED_EVENT → MAIN

7大会。

SEED_EVENT完了後にのみMAINをactivateする。

### SEED_EVENT → FIRST_TOURNAMENT → MAIN

岐阜秋 CMP000110。

- 地区seed戦で16seed
- 非seed校のみFMT026 gate
- gate winner＋seed校でMAIN

### SEED_EVENT → PRELIMINARY_QUALIFIER → MAIN

愛媛秋 CMP000144。

- SEED_EVENTで12seed
- seedを予選16blockへ分散
- 予選winner16校でMAIN
- seed metadataはMAINへ持ち越さない

## Lazy boundary

prepare直後:

- MatchResolver call 0
- SEED_EVENT以外未生成
- gate未生成
- qualifier未生成
- MAIN未生成

SEED_EVENT完了後:

- graphに応じてgate / qualifier / MAINをactivate

gate / qualifier完了後:

- MAIN entrants確定
- MAIN bracket生成

## Legacy equivalence

対象9大会すべてについて、

- legacy TournamentEngine.run()
- lazy prepare_seeded_competition_runtime().resolve_all()

のCompetitionRun.to_dict()が完全一致。

岐阜秋はdetailed MatchResolutionでもresolver call sequenceとmatch_simulation_resultsが一致した。

## CIでの修正

初回CIでは岐阜秋のみStageExecution差分が発生した。

原因はSingleRoundGateRuntimeStateが内部で保持するentrant_school_idsがgate draw後のshuffle順であり、legacy StageExecutionはdraw前のnonseed順を保存していたこと。

勝敗・seed assignment・MAIN entrantsは一致していた。

SeededCompetitionRuntimeStateでgate_entrant_school_idsの元順を別保持し、StageExecutionだけlegacy契約の元順を使用するよう修正した。

修正後:

- Stage 13E-3B-3専用テスト: 7件
- full suite: Ran 518 tests in 19.819s
- OK

## 次工程

Stage 13E-3C:

competition runtimeをSeasonRuntimeState / competition scheduleへ接続し、current_dateに応じてpre-MAINからMAINまで実際に試合を発火する。
