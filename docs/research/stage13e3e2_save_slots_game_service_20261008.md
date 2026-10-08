# Stage 13E-3E-2 Save Slots / Game Service 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/save_slots.py
- phase2_engine/live_game_service.py
- tests/test_stage13e3e2_save_slots_game_service.py

更新:

- phase2_engine/live_season_save.py
- phase2_engine/__init__.py

## SaveSlotManager

slot directory内に

- manual.json
- autosave.json
- backups/manual.NNN.json
- backups/autosave.NNN.json

を管理。

manual/autosaveは独立。

max_backups default=3。

slot id path traversal guard追加。

## metadata inspection

inspect_live_season_save()を追加。

save全体をrestoreせずに

- year
- seed
- current_date
- resolver contract
- processed count
- completed match count
- checksum
- summary

を取得可能。

## latest

manual/autosave primaryのgame state比較で決定。

current_date → processed count → autosave priority。

mtime非依存。

## LiveGameService

追加API:

- new_game
- load_game
- save_game
- autosave_game
- play_today
- next_day
- advance_to
- advance_through
- list_games
- delete_game

操作完了後autosaveをdefault有効。

per-callでautosave=False可能。

## Regression

### new/load

new_gameでmanual initial save。

next_dayでautosave。

latest=autosave。

latest load後のpublic snapshot / history一致。

### manual backup

max_backups=2。

複数manual save後:

- backup 1 = 直前
- backup 2 = 2世代前
- 3世代以前なし

backup 2からruntime復元成功。

### autosave backup

7/1 manualを保持したままautosaveを3回更新。

- autosave primary 7/4
- backup 1 7/3
- backup 2 7/2
- manual primary 7/1

を確認。

### policy

advance_to autosave=Falseでsaveなし。

play_today autosave=Trueでsave作成。

### slot lifecycle

list_games順序・delete_game・invalid path拒否を確認。

### production full-season

実LiveSeasonGraphPlannerからservice new_game。

- templates 162
- active 131
- waiting 31
- initial manual save 2026-01-01

を確認。

## Automated validation

Stage 13E-3E-2専用テスト: 6件。

full suite:

- Python 3.12
- Ran 555 tests in 33.233s
- OK

## 判断

Stage 13E-3E-2を採用する。

これで正式GUI/CLIはsave JSONやplanner内部を直接扱わず、
LiveGameServiceをゲームライフサイクル境界として利用できる。

## 次工程

Stage 13E-3E-3ではCLI/metadata/migration/recovery contractを候補とする。
