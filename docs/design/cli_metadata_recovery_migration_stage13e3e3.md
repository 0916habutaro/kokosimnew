# Stage 13E-3E-3 CLI / user metadata / recovery / migration

作成日: 2026-10-08

## 目的

Stage 13E-3E-2で、

- SaveSlotManager
- manual / autosave primary
- rolling backup
- LiveGameService
- new/load/save/autosave
- 日付進行

まで実装した。

Stage 13E-3E-3では、正式GUIの「新規ゲーム」「続きから」「復旧」が利用する前段契約として、

- user-facing slot metadata
- recovery source inventory
- corrupt save isolation
- recovery promotion
- save schema migration registry
- game service CLI

を追加する。

## user-facing slot metadata

save payload本体とは別に

`slot_metadata.json`

をslot directoryへ置く。

保持項目:

- slot_id
- title
- created_at
- last_saved_at
- last_source
- year
- rng_seed
- current_date

### 分離理由

titleやwall-clock timestampはゲーム結果再現に必要ない。

save v1 payloadへ含めると、

- title変更だけでpayload checksumが変わる
- user-facing metadata破損がgame state復元を妨げる
- 将来UI項目追加がsave schema migrationを要求する

ため、補助ファイルとして分離する。

### 非正本

`slot_metadata.json` は非正本。

JSON破損・型不正時は `read_user_metadata()` がNoneを返す。

save本体が正常なら、

- slot listing
- latest selection
- load
- recovery

は継続できる。

次回saveでmetadataは再生成可能。

## slot title

new_game():

`title="2026年シーズン"`

を指定可能。

未指定時はslot_idをtitleとして使用。

rename_game():

game stateを変更せずtitleだけをatomic updateする。

created_atは維持する。

## SaveSlotFile validity

Stage 13E-3E-2ではprimary inspect失敗がslot_summary全体へ例外伝播した。

3E-3ではSaveSlotFileへ

- status
- error

を追加。

status:

- missing
- valid
- invalid

primary saveが壊れていてもslot自体は一覧可能。

例:

- manual valid
- autosave invalid

ならlatest_sourceはmanualになる。

## recovery source inventory

`SaveSlotManager.recovery_sources(slot_id)`

で存在する全sourceを列挙する。

対象:

- manual
- autosave
- manual_backup_N
- autosave_backup_N

各source:

- source
- path
- status
- error
- metadata

を返す。

破損sourceも除外せずstatus=invalidとして返す。

正式GUIでは、

- 通常ロード候補
- 破損候補
- backup復旧候補

を同一画面で表示可能。

## recovery promotion

`LiveGameService.recover_game()`

1. 指定backupをdeterministic replay load
2. 正常復元を確認
3. manualまたはautosave primaryへsave
4. 現primaryは通常のrolling backupへ退避

する。

復旧時に現在primaryを即削除しない。

例:

manual primary = 7/3
manual_backup_2 = 7/1

7/1をrecoverすると、

- new manual primary = 7/1
- manual_backup_1 = 旧primary 7/3

となる。

復旧操作自体もundo可能な形を優先する。

## save migration registry

`SaveMigrationRegistry`

を追加。

### register

`register(from_version, to_version, migrate)`

1 from versionにつき1 step。

同じfrom versionへの重複登録は禁止。

### path

from → targetまで明示stepを辿る。

- targetと同一schema: no-op
- step欠落: SaveMigrationError
- cycle: SaveMigrationError

### migrate

payloadをdeepcopyし、各migration functionを順番に適用する。

migration functionはdictを返し、
返却schema_versionがregistered to_versionと一致する必要がある。

### runtime integration

以下のvalidate前にmigrationを通す。

- restore_live_season_save()
- inspect_live_season_save()
- read_live_season_save()

未知schemaはLiveSeasonSaveCompatibilityErrorへ変換する。

### current v1

2026-10-08時点で正本schemaは

`stage13e3e1.live-season-save.v1`

のみ。

DEFAULT_SAVE_MIGRATION_REGISTRYにはhistorical migrationをまだ登録しない。

current v1 → current v1はno-op。

registryは将来v2導入時の正式入口として先行固定する。

## migration checksum helper

`rechecksum_live_season_save_payload()`

を公開。

migration functionがpayload変換後に

- old payload_checksum削除
- canonical JSON SHA-256再計算

できる。

注意:

future historical migrationでは、
旧schema integrity checkをmigration function側または旧schema validatorで
行う設計を追加できる。

3E-3ではmigration pipeline contractの固定を目的とする。

## migration regression

testではfake legacy:

`stage13e3e0.live-season-save.v0`

を作る。

custom registry:

v0 → current v1

を登録。

migration functionは

1. schema_version更新
2. checksum再計算

を行う。

restore後、

- plan snapshot
- runtime public snapshot

が元v1 stateと完全一致。

unknown.save.v9はmigration pathなしとして拒否する。

## game service CLI

module:

`python -m phase2_engine.live_game_cli`

CLI独自のgame logicは持たない。

必ずLiveGameServiceを呼ぶ。

### global options

- --data-dir
- --save-root
- --year
- --resolver-contract
- --max-backups

### commands

#### new

`new SLOT --seed N [--start-date DATE] [--title TITLE]`

full-season plan/runtimeを生成しinitial manual save。

#### list

slot summary一覧。

#### status

`status SLOT [--source latest]`

runtime replayなしでsave metadata inspect。

#### recoveries

primary / backup validity一覧。

#### rename

user-facing title変更。

#### save

指定sourceをloadしmanual primaryへsave。

#### recover

`recover SLOT --source manual_backup_2 [--kind manual]`

backupをprimaryへ昇格。

#### play-today

latest gameをloadし当日試合を処理。

#### next-day

latest gameをloadし当日処理＋翌日へ。

#### advance-to

target date直前まで処理しtarget dateをcurrentにする。

#### advance-through

target dateを含めて処理する。

#### delete

`--confirm` 必須。

誤削除防止をCLI契約に含める。

## CLI output

stdoutへUTF-8 JSON。

dataclass / to_dict object / PathをJSON変換可能にする。

GUIとは異なるsurfaceだがservice contract検証・手動デバッグ・save復旧運用に利用できる。

## regression

### metadata lifecycle

new_game title:
宮城テスト

rename:
2026年シーズン

確認:

- title更新
- created_at維持
- autosave後last_source=autosave
- current_date更新
- save本体payloadにtitleなし

### corrupt source isolation

autosave.jsonを壊す。
slot_metadata.jsonも壊す。

確認:

- autosave status=invalid
- manual status=valid
- latest=manual
- user_metadata=None
- autosave_backup_1はvalid
- latest loadでmanualから正常復元

### recovery promotion

manual backup 2の7/1をprimaryへ昇格。

確認:

- primary 7/1
- 旧primary 7/3がbackup 1

### CLI

run_command()をmini serviceへ接続。

- new
- list
- next-day
- status
- recoveries
- rename
- delete confirmation

を検証。

## 次工程

Stage 13E-3F候補:

- full-season live E2E audit
- calendar_gap / waiting dependency blocking analysis
- pre-MAIN 49 stageのverified化優先順位決定
- live runtimeから正式GUI用read model projection
- game service home/status API

Stage 13E-3Eとしては、
保存・再開・slot・autosave・backup・recovery・CLI・migration入口まで完了。
