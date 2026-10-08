# ADR-028: user metadataとgame state saveを分離し、復旧候補は破損状態も列挙する

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3E-3

## Context

正式GUIの「続きから」画面では、

- セーブ名
- 最終ゲーム日
- manual/autosave
- backup
- 破損save

を表示する必要がある。

user-facing titleやwall-clock timestampをgame state saveへ入れると、
表示名変更だけでchecksumやsave compatibilityへ影響する。

またprimary saveが破損した時にslot listingそのものが例外になると、
backupへ復旧するUIを表示できない。

save schema versionが将来増える場合も、
ロード本体へad-hocなif文を追加し続けるのは避けたい。

## Decision

### metadata separation

user-facing metadataは

`slot_metadata.json`

へ分離する。

game state JSONを正本とし、metadataは補助情報とする。

metadata破損はgame state load failureにしない。

### corrupt source isolation

SaveSlotFileは

- missing
- valid
- invalid

を明示する。

slot summaryは1つのprimaryが破損しても、
他primaryが正常なら継続して生成する。

### recovery inventory

存在するprimary / backupを全件列挙する。

invalid sourceも隠さず、

- error type
- error message

を返す。

復旧UIが利用者へ状態を説明できることを優先する。

### recovery promotion

backup復旧はload検証後にprimaryへsaveする。

旧primaryはrolling backupへ残す。

### schema migration

save schema変更はSaveMigrationRegistryの明示stepでのみ行う。

migration pathが無いversionをbest effortで読み込まない。

## Consequences

### Positive

- title変更がgame state checksumへ影響しない
- metadata破損でもsave復旧可能
- corrupt autosaveからmanualへfallback可能
- backup recovery UIを構築しやすい
- migration経路が監査可能
- unknown schemaを曖昧に解釈しない
- CLIと将来GUIが同一service contractを共有

### Trade-offs

- slot directory内ファイル数が1つ増える
- metadataとsave primaryの更新は完全なmulti-file transactionではない
- metadataは非正本なのでsaveから再構築する場合がある
- v1以前の実historical migrationはまだ存在しない

## Follow-up

正式GUIではrecovery_sources()を使い、
破損sourceを警告表示した上でvalid backupを選択できるようにする。

将来v2導入時はADRとmigration stepを同時追加する。
