# ADR-027: manual saveとautosaveは同一slot内で独立した世代チェーンを持つ

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3E-2

## Context

ゲームでは直近状態を自動保存したい一方、
プレイヤーが意図的に残したmanual saveをautosaveで上書きすると
任意の復帰点を失う。

単一save fileだけでは、

- 操作直後の最新状態
- 手動で残した安全な復帰点
- save破損前の旧世代

を同時に保持できない。

またGUIが直接ファイル名やplannerを操作すると、
永続化規約がUI実装へ漏れる。

## Decision

1 slot directory内に

- manual primary
- autosave primary
- manual rolling backups
- autosave rolling backups

を独立して保持する。

default max_backupsは3。

primary上書き前に旧primaryをgeneration 1へ退避する。

backupはlatest loadへ自動採用せず、
recovery sourceとして明示選択する。

ゲーム操作はLiveGameServiceへ集約し、
GUI/CLIは

- new_game
- load_game
- save_game
- autosave_game
- date progression

をservice越しに行う。

## latest policy

通常の「続きから」はmanual/autosave primaryのうち
最も新しいgame stateを選ぶ。

比較:

1. current_date
2. processed_date_count
3. autosave priority

filesystem mtimeはsave state orderingの正本にしない。

理由:

- file copyでmtimeが変わり得る
- cloud sync等でmtimeが変わり得る
- game timeのほうが意味的に安定

## Autosave timing

Stage 13E-3E-2ではpublic service action完了時にautosaveする。

複数日advanceの内部1日ごとには保存しない。

## Consequences

### Positive

- manual saveをautosaveが破壊しない
- 直近autosaveから通常再開できる
- 旧世代へ明示復旧できる
- backup数が上限付き
- GUIからfilesystem規約を分離
- save schema検証を全経路で再利用
- cloud/OSのmtime依存を避ける

### Trade-offs

- 1 slotあたり複数JSONを保持する
- replay型saveのため各backup loadにも復元コストがある
- user-facing slot名やtimestampはまだ未実装

## Follow-up

将来のslot metadataはsave本体とは別の軽量indexへ追加できる。

その場合もmanual/autosave primaryのsave schema v1は変更せず、
metadata破損がゲーム本体saveを壊さない構成を優先する。
