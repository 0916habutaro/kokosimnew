# Stage 13E-3E-2 save slots / autosave / game service

作成日: 2026-10-08

## 目的

Stage 13E-3E-1でfull-season live runtimeのJSON save/load v1を実装した。

ただし呼び出し側は、

- save file path
- manual/autosaveの区別
- backup世代
- planner再構築
- new/load/save操作

を直接扱う必要があった。

Stage 13E-3E-2では、将来の正式GUI/CLIがruntime内部を知らずに
ゲームを開始・保存・再開できるservice contractを固定する。

## SaveSlotManager

1 save slotを1 directoryとして管理する。

標準配置:

```text
<save_root>/
  <slot_id>/
    manual.json
    autosave.json
    backups/
      manual.001.json
      manual.002.json
      manual.003.json
      autosave.001.json
      autosave.002.json
      autosave.003.json
```

manualとautosaveは独立したprimary / backup chainを持つ。

### slot_id

許可:

`[A-Za-z0-9][A-Za-z0-9_-]{0,63}`

理由:

- path traversalを禁止
- OS依存記号を避ける
- GUI表示名とfilesystem keyを分離しやすくする

表示用の日本語セーブ名は将来slot metadataへ追加できる。
v1 slot id自体はfilesystem-safe keyとする。

## manual save

`SaveSlotManager.save(..., kind="manual")`

新しいmanual saveを書く前に既存manual primaryを
manual.001へ複製する。

既存backupは

- .001 → .002
- .002 → .003

の順でrotateする。

max_backupsを超える最古世代を削除する。

新save本体はStage 13E-3E-1の
write_live_season_save()を使い、temp fileからatomic replaceする。

## autosave

`SaveSlotManager.autosave()`

manualと同じsave schemaを使うが、
primary / backup chainはautosave専用。

manual saveをautosaveが上書きしない。

この分離により、

- プレイヤーが明示保存した復帰点
- 直近の自動保存

の両方を保持できる。

## latest source

`source="latest"` はmanual/autosave primaryだけから選ぶ。

比較順:

1. current_date
2. processed_date_count
3. autosave priority

同一game date / processed countならautosaveを優先する。

理由:

同一日でもautosaveは通常ユーザー操作後の最新状態である可能性が高い。

backupはlatest candidateへ自動昇格しない。
破損時などに利用者/復旧UIが明示選択する。

## backup source

明示load source:

- manual
- autosave
- latest
- manual_backup_1
- manual_backup_2
- ...
- autosave_backup_1
- autosave_backup_2
- ...

世代1が最も新しい旧save。

## save metadata inspection

Stage 13E-3E-1へ

`inspect_live_season_save(path)`

を追加。

restore前にchecksum/schemaを検証して次を取得できる。

- schema_version
- year
- rng_seed
- resolver_contract
- start_date
- current_date
- processed_date_count
- completed_match_count
- plan_fingerprint
- payload_checksum
- runtime_summary

SaveSlotManagerの一覧表示とlatest判定に利用する。

## LiveGameService

正式GUI/CLI向けfacade。

保持:

- DataRepository
- data_dir
- save_root
- year
- resolver_contract
- max_backups
- autosave_after_action
- planner factory

公開操作:

### new_game

`new_game(slot_id, rng_seed, start_date=None, engine=None, save_initial=True)`

1. LiveSeasonGraphPlanner生成
2. full plan生成
3. live runtime生成
4. LiveGameSession作成
5. 既定ではmanual initial save

2026 full planでは162大会を呼び出し側が手作業で列挙する必要はない。

### load_game

`load_game(slot_id, source="latest", engine=None)`

1. slot save metadata inspection
2. saved year/rng_seed取得
3. planner再構築
4. resolver_contract確認
5. Stage 13E-3E-1 deterministic replay restore
6. LiveGameSession返却

### save_game

manual/autosave kindを指定可能。

通常GUIの「保存」はmanualを使用する。

### autosave_game

autosave primaryへ保存する。

### play_today / next_day / advance_to / advance_through

runtime actionをservice経由で呼び、
操作完了後に既定でautosaveする。

`autosave=False`で操作単位に抑止可能。

### list_games

SaveSlotSummary一覧を返す。

GUIの「続きから」画面はruntimeをloadせずに

- manual metadata
- autosave metadata
- latest_source

を表示できる。

### delete_game

slot directory全体を削除する。

将来GUIでは削除確認をUI側で行う。

## autosave boundary

Stage 13E-3E-2では「service operation完了後」をautosave境界とする。

例:

- next_day()
- play_today()
- advance_to()
- advance_through()

内部でadvance_toが複数日進めても、
毎日saveするのではなくpublic operation完了時に1回autosaveする。

理由:

- I/O回数を抑える
- rolling backupの消費を抑える
- GUI操作のtransaction boundaryと一致する

将来「毎日autosave」設定を追加する場合は
service policyとして別実装可能。

## LiveGameSession

保持:

- slot_id
- LiveSeasonGraphPlan
- LiveSeasonDependencyRuntimeState
- resolver_contract

GUIはsession.stateのread APIを利用できるが、
new/load/save lifecycleはLiveGameServiceを正本とする。

## planner_factory

本番はLiveSeasonGraphPlannerを使用する。

テストではplanner_factory injectionを許可する。

目的:

- 小さいdependency graphでfile lifecycleを高速検証
- production planner contractは変更しない

## validation

### lifecycle

new_game:

- initial manual save作成
- autosaveなし

next_day:

- current_date +1
- autosave作成
- latest=autosave

load latest:

- public snapshot一致
- history一致

### manual rolling backup

max_backups=2で3回上書き。

最終:

- primary: current
- manual_backup_1: 直前
- manual_backup_2: 2世代前
- それ以前: 削除

manual_backup_2からruntimeを復元できる。

### autosave independent chain

manual primaryは7/1のまま、
autosaveを7/2→7/3→7/4と更新。

最終:

- autosave primary: 7/4
- backup 1: 7/3
- backup 2: 7/2
- manual primary: 7/1

### autosave policy

advance_to(..., autosave=False)ではautosaveを作らない。

その後play_today(..., autosave=True)で作成する。

### slot safety

`../escape`等のinvalid slot idを拒否する。

listはvalid directoryのみを対象にする。

### full-season startup

実LiveSeasonGraphPlannerでnew_game。

確認:

- template competition: 162
- active runtime: 131
- waiting dependency: 31
- initial manual save: 2026-01-01

## 次工程

Stage 13E-3E-3候補:

- game service CLI
- save slot display metadata
  - user-facing title
  - created_at / last_saved_at
  - play time
- autosave trigger settings
- recovery UI contract
- save schema migration registry
- BrowseRepository snapshot同期

正式GUI実装前に、起動・永続化serviceの境界をさらに固定する。
