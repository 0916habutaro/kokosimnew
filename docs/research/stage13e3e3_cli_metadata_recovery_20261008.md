# Stage 13E-3E-3 CLI / Metadata / Recovery / Migration 実装報告

作成日: 2026-10-08

## 実装

新規:

- phase2_engine/save_migrations.py
- phase2_engine/live_game_cli.py
- tests/test_stage13e3e3_cli_metadata_migration.py

更新:

- phase2_engine/live_season_save.py
- phase2_engine/save_slots.py
- phase2_engine/live_game_service.py
- phase2_engine/__init__.py

## User metadata

slot_metadata.jsonを追加。

title / created_at / last_saved_at / last_source / year / seed / current_date。

save payloadから分離。

metadata JSON破損時はNoneとして扱い、
game state load/recoveryを継続可能。

## Corrupt primary isolation

SaveSlotFileへstatus/errorを追加。

autosaveが破損していてもmanualがvalidならlatest=manual。

slot listing自体を失敗させない。

## Recovery inventory

manual/autosave primaryとrolling backupを一覧化。

各sourceをvalid/invalidで表示。

testでは破損autosave primaryとvalid autosave_backup_1を同時確認。

## Recovery promotion

backup sourceをload検証後primaryへ昇格。

旧primaryはbackup 1へ残る。

7/1 backupを復旧した際、
旧7/3 primaryがbackup 1になることを確認。

## Migration

SaveMigrationRegistryを追加。

current schemaはno-op。

fake v0→v1 migrationでruntime完全復元を確認。

unknown schemaはCompatibilityError。

rechecksum helperを公開。

## CLI

live_game_cliを追加。

commands:

- new
- list
- status
- recoveries
- rename
- save
- recover
- play-today
- next-day
- advance-to
- advance-through
- delete

CLIはLiveGameServiceのみを利用。

## CI issue / fix

初回CI:

- Ran 561 tests
- 1 error

原因:

CLI testがnext_day()の既存返却契約をcurrent_dateと誤認。

実契約は

- from_date
- to_date
- played_match_count

修正:

テストをto_dateへ合わせた。

runtime/service実装変更なし。

再CI:

- Ran 561 tests in 33.743s
- OK

## 判断

Stage 13E-3E-3を採用する。

これにより、正式GUIの

- 新規ゲーム
- 続きから
- save名表示
- autosave/manual判定
- backup選択
- 破損save警告
- 復旧
- 将来schema migration

が既存service contract上で実装可能になった。

## 次工程

Stage 13E-3Fで年間live runtimeのE2E blocker監査へ進み、
49件のpre-MAIN calendar gapがどの大会依存を止めるかを可視化するのが優先候補。
