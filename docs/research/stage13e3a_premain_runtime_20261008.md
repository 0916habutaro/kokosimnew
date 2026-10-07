# Stage 13E-3A pre-MAIN runtime 実装報告

作成日: 2026-10-08

## 実装

追加:

- phase2_engine/premain_runtime_common.py
- phase2_engine/premain_runtime_single_elim.py
- phase2_engine/premain_runtime_gate.py
- phase2_engine/premain_runtime_round_robin.py
- phase2_engine/premain_runtime_forest.py
- phase2_engine/premain_competition_runtime.py
- tests/test_stage13e3a_premain_runtime.py

TournamentEngineへ追加:

- prepare_qualifier_main_runtime()

## 対応

共通primitive:

- single elimination
- single round gate
- round robin
- block winner forest

competition graph:

- FMT001 qualifier → MAIN

## Legacy equivalence

primitive単位で既存brackets.pyと比較:

- ranking / winners一致
- Match list一致
- detailed result sink一致

実大会fixture:

北海道春 CMP000004

legacy TournamentEngine.run()
と
prepare_qualifier_main_runtime().resolve_all()
のCompetitionRun.to_dict()を完全比較し一致。

## Lazy boundary

prepare直後:

- resolver calls = 0
- qualifier future winnerなし
- pre_main_match_simulation_results={}
- main_runtime=None
- main_entrant_school_ids=[]

全qualifier group完了後のみMAIN runtimeをactivateする。

## GitHub Actions

- Stage 13E-3A専用テスト: 8件
- full suite: Ran 501 tests in 21.143s
- OK

## 判断

Stage 13E-3Aを採用する。

次はStage 13E-3BでFMT006 pool RR + cross playoffと、複合phase format / seed event / gate graphをcompetition runtimeへ接続する。
