# 初回GitHub投入セット 移管報告

作成日: 2026-10-05

## 入力順
1. `high_school_baseball_phase1_completed_20261004.zip`
2. `high_school_baseball_phase2_stage12f_tokyo_preliminary_20261005.zip`
3. Stage 12G 東北3CSV

## Phase 1 -> Stage 12F整合
Phase 1完成ZIPの132ファイル中、Stage 12Fにも存在する131ファイルをSHA-256比較し、差分は **0**。
Stage 12FはPhase 1完成データを変更せず累積していることを確認。

## Stage 12G統合
- 東北6県 x 春秋 = 12大会を `prefectural_competition_index_2026.csv` から正式competition_idへ紐付け
- `season_calendar.csv` の12行を `official_schedule` へ更新
- 日単位の92レコードを `stage12g_tohoku_match_days_20261005.csv` として格納
- Stage 12F時点 `official 3 / pending 91` -> **official 15 / pending 79**
- 未登録だった一次資料URL 7件を `phase2_sources.csv` に追加

## 構造整理
Stage 12FのフラットCSVを `data/master`, `data/areas`, `data/competitions`, `data/schedules`, `data/sources` に整理。
`phase2_engine.paths.resolve_data_file()` を追加してエンジンから新配置を解決する。Pythonパッケージ自体は初回移管で不要な挙動変更を避けるため `phase2_engine/` のまま維持。

## 移管検証
Phase 2 Stage 12F原本: 70テスト PASS。
構造整理・Stage 12G統合後は `tests/test_stage12g_tohoku_schedule.py` 4件を追加し、**74/74テスト PASS**。

`python -m phase2_engine.season_cli --data-dir data --year 2026 --seed 2026100501` もPASSし、県春秋94大会完走・calendar gap 79を確認。

Stage 12B時点の `phase2_rule_engine_reference.py --validate` はStage 12F原本でも固定件数前提によりFAILするため、現行ツールから `archive/legacy_tools/` へ移した。
