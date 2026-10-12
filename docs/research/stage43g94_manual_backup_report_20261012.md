# Stage43G-94：手動独立バックアップ実装報告

Issue #243、基点main `2854ee77ae90ac037ce30b946f2e471debe4f3ab`。方式Aを限定採用し、停止済み単大会の旧A slotへ手動API/独立CLIとread-only候補validatorを追加した。[設計](stage43g94_manual_backup_design_20261012.md)、[使用例](../../README.md)、[ADR-033](../adr/ADR-033-manual-independent-backup-adoption.md)を参照。

## 実装・対象・保全

変更はmanual_save_backup（診断/export/verify）、legacy_backup_oracle（独立SQL/SHA）、legacy_backup_compatibility（固定許可名と集合版チェックによる338ファイル）、fixture専用audit/runner、両OS CI、日本語文書・ADR・README・測定JSON。既存ゲームwriter・保存schema・load/replay経路は変更していない。

現行v1/default resolver契約の単大会liveを、manual/autosave、封印後、隣接翌年登録後の6状態で検証した。存在する両live系列・全rolling backups、全年度/全試合Option A、年度identity/ledger/outcomes、全roster/player identity、現在の固定互換入力を保存する。派生cache/索引は不使用。career/multi preview/地域feeder/年度continuity/架空v2混在/unknown file・table・versionは拒否する。

原本はimmutable read-only＋query_only、DBコピーはSQLite backup API。原本一覧/SHA前後一致、コピーの全SQL行/schema一致、既存inventoryと独立oracleによる台帳/Option A/roster/checkpoint照合を確認した。生SQLite copy、load_gameによるarchive sync、元saveの修復は行わない。

独立新規pathを排他的作成し、既存空directoryも拒否する。同時実行は一方だけ成功。ENOSPC/EIO/KeyboardInterrupt、backup/receipt失敗、copy中writer commit、最終変更、出力改変、再実行衝突を試験した。失敗候補・旧履歴を削除しない。完了receipt/evidenceは署名なしの整合性資料で、保存世代manifestやrestore承認ではない。

## 件数・OS・CI

| 検証 | 件数 | 記録 |
|---|---:|---|
| 新規手動API/CLI・障害・拒否 | 38 | Linux成功・skipなし、manual_linux_20261012.json |
| Stage91/92/93・89・実Tk GUI | 104 | Linux成功・skipなし、regressions_linux_20261012.json |
| 年度登録/継続・旧A年次 | 37 | Linux成功・skipなし、annual_linux_20261012.json |
| GUI明示handle cleanup runner | 15 | Linux成功・skipなし、gui_linux_20261012.json |
| 関東8都県17校E2E | 2 | Linux成功・skipなし、477.247秒、kanto17_20261012.json |
| 全Python 3.12 unittest | 2143 | 関東2件は専用実行へ分離。Linux全体＋spawn再検証成功、full_unittest_20261012.json。最終headのPython CIでも照合 |

重複行は合算しない。新規38件は全体2143件にも含む。すべて自己生成TemporaryDirectoryのsaveだけを入力した。小規模fixtureは8校単大会で、関東実E2Eと同一規模とは表示しない。

専用manual-save-backup.ymlはubuntu/windows各々で新規38、Stage91/92/93、年次37、実Tk GUI15を実行し、成功・件数・skipゼロ・source zero-write/no-clobberをassertする。Stage89は既存Linux専用19件をLinuxで全assertionを維持して確認する。Windowsの短縮pathとopen DB renameを仮定しないStage94の契約と分け、無関係なv2 Windows対応は追加しない。既存python-tests.ymlは全unittestと関東専用を実行する。Windowsは固定互換byteを保持し、junction/hardlink拒否とhandle解放を確認する。GUI旧fixtureはnative接続をassertion後/tearDown前に閉じる専用runnerを使い、製品writerをpatchしない。

最終headの全CI成功を完了条件とし、証跡はPR Checksと両OS専用artifactのJSONで確認する。local測定とCI時間は別sampleで、Windows成功をLinuxから推定しない。PRは成功後も未マージ・auto-mergeなしでレビュー待ちにする。

localの初回GUI追加検証はサンドボックスによるX11起動/接続拒否で失敗した。TCP無効の仮想displayと接続可能な実行条件で再実行し、104件・15件が成功した。assertionを弱めていない。全unittestのlocal集計は初回stdin実行器をmultiprocessing spawnが再読込できず、Stage90の3件/25境界がエラーになった。実ファイルのguard付き実行器でStage90全15件を再検証し成功した。初回2143件と15件再検証をJSONに両方保持し、2143件の単発成功と偽らない。CIは通常のpython -m unittestで全体を確認する。

master CSV106ファイルの集合とbyteは不変。実path/SHAは非公開で、protected_inputs_20261012.jsonに件数と一致だけを記録した。添付作業領域の既存save4は0件で、その不変性を確認したと主張しない。ユーザー実saveをテスト入力にしていない。

## 測定・未保証・次Stage

6状態のcopy＋照合は約0.54–0.71秒。原本slotは約1.33–3.52MiB、互換入力338ファイルは約7.29MiB、候補総量は約8.66–10.85MiB、原本＋当該候補の観測合計は約9.99–14.37MiB。詳細はaudits/phase2/stage43g94/manual_linux_20261012.json。候補総量にはprivate evidence/receiptを含む。時間は最終照合/完了境界まで、合計はFS割当・メモリ・既存repo・一時journal・他候補を含む普遍的ピークではない。

停止宣言と前後SHAは真のwriter排他を証明しない。全writer停止済みslotでだけ使う。無停止・複数DB同時点、最終観測後の変更/TOCTOU/ABA、所有者/全履歴の真正性、生成時外部版一致、途中career/他PC完全再開、NFS/電源断/fsyncは未保証。成功でもrestore承認・全ゲーム再開証明はfalse。全国100/200年実進行は追加測定せず、保存年数無制限を維持する。

自動backup/restore、元save上書き・移行・履歴削除、世代manifest/共通slot lock、方式B/C、正式GUI、import/activationは追加していない。次Stage候補は自己生成fixtureの新規隔離directoryだけで手動restore候補をコピーしread-onlyに照合する実験。本番restoreは別判断。
