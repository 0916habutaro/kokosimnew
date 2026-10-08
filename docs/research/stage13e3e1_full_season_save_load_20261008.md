# Stage 13E-3E-1 Full-season Save/Load 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/live_season_save.py
- tests/test_stage13e3e1_full_season_save_load.py

更新:

- phase2_engine/__init__.py

## schema

stage13e3e1.live-season-save.v1

JSON。

pickle不使用。

## save content

- year
- rng_seed
- resolver_contract
- plan_fingerprint
- start_date
- current_date
- processed_dates
- completed_match_results
- status_by_competition
- activated_on
- runtime_summary
- public_snapshot_fingerprint
- history
- payload_checksum

completed_match_resultsにはability_detailを含む。

pending/future resultは保存しない。

## restore

plannerからfresh plan/runtimeを生成。

processed dateまでreplay。

その後saved stateと以下を照合:

- completed results
- dependency statuses
- activation dates
- public snapshot
- runtime summary

一致後にsaved historyを復元。

## mid-day boundary

宮城mini graphで

advance_to(2026-07-28)

をsave pointとした。

この時点では7/27までprocessed、
current_dateは7/28だが当日は未処理。

restore後も同じ状態。

play_today()後に両方でCMP000077が同じ夏優勝校をdirect entryとしてactivate。

current_dateとprocessed-throughの差を正しく保持できる。

## file roundtrip

7/28処理後を

write_live_season_save()

で.tmp→replace。

read_live_season_save()で復元。

public_snapshot / history一致。

さらに8/2まで継続し一致。

## resolver detail

custom deterministic resolver:

- 4-2 score
- score_source=save_test_v1
- detail.save_test_marker

を保存。

load時も同resolver contractで再演算し、
ability_detailを含むcompleted match record完全一致。

## corruption guards

確認済み:

- checksum改ざん → SchemaError
- planner output変更 → CompatibilityError
- resolver contract変更 → CompatibilityError
- resolver結果変更 → ReplayError
- match resultを改ざんしchecksumも再計算 → ReplayError

checksumだけに依存せずruntime replayと二重検証する。

## Automated validation

Stage 13E-3E-1専用テスト: 5件。

full suite:

- Python 3.12
- Ran 549 tests in 33.960s
- OK

## 判断

Stage 13E-3E-1を採用する。

これでfull-season runtimeは
ゲーム終了時に保存し、同じmaster / resolver contractで
完全状態へ復元して続行可能になった。

## 次工程

Stage 13E-3E-2:

- save slot manager
- autosave
- rolling backup
- new/load/save game facade
- schema migration入口

を候補とする。
