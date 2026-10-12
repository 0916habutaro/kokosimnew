# Stage43G-94：停止済み旧Aスロットの手動独立バックアップ

Issue #243。最新main `2854ee77ae90ac037ce30b946f2e471debe4f3ab`（PR #242マージ）から専用ブランチを作成した。限定採用範囲は[ADR-033](../adr/ADR-033-manual-independent-backup-adoption.md)。Stage91の[正本inventory](stage43g91_save_inventory_design_20261012.md)、Stage92のwriter修正、Stage93の[静止export実験](stage43g93_quiescent_export_design_20261012.md)を引き継ぐ。

## 製品入口と初期サポート

`phase2_engine.manual_save_backup` に `diagnose_backup`、`export_backup`、`verify_candidate` と独立CLIを追加する。通常のゲーム起動・保存・GUIからのhookはない。root・slot・manual/autosave・新規出力を明示し、停止宣言がなければ読取前に拒否する。latestやbackup番号の自動選択はない。

初期対象は現行v1 JSON、既知の `default_deterministic_v1` resolver契約、**単大会の旧A live経路**。runtime大会数は1、qualification / regional feeder / regional playoff / resolution件数は0を要求する。resolver名は既存サービスの契約文字列で、注入engineまで識別する署名ではない。完全Aを生成する能力モデルの8校単大会を、実LiveGameServiceのnew→play→save→sync→sealで試験する。

選択系列と当年archiveの試合集合・各結果が完全一致し、roster/identityと全年度台帳が整合する場合だけ候補を作る。隣接翌年登録まで保持するが、翌年の大会再開は未検証。複数大会live、途中career、multi preview、地域予選・feeder、参加manifest、年度rulebook/continuity/preflight、架空v2混在は拒否する。未選択liveとrolling backupsは古くても全保存し、各々の年度seed/resolver/planをarchiveの同年度metadataと照合する。

旧JSONにはslot IDがない。表示metadataにIDがあれば照合するが、metadataのない同一内容の別slotや、整合的に切り落とされた過去年を内容だけで識別できない。取得時のprivate pinは取得以前の所有者・全履歴の真正性を証明しない。

## 正本・互換入力の集合

| 集合 | 保全・判定 |
|---|---|
| manual / autosave JSON | 存在する両系列を原byteで保存。選択した一方を当年archiveと比較 |
| backups/manual.NNN.json・autosave.NNN.json | 全保存。checksum/schema/年度identityを確認。現在DBと同時点の候補とは扱わない |
| historical_matches.sqlite3 | archive_identity、全career_years、全年度・全試合Option A、存在するoutcomes、DB内indexをbackup APIで保持 |
| career_rosters.sqlite3 | 全学校年度roster・全player identityをbackup APIで保持。全試合成績の所属を年度rosterと独立照合 |
| slot_metadata.json | 存在すれば原byteで保持。表示時刻は世代証明に使わない |
| 既知の派生stats / 学校索引namespace | 原本側の不変性監査対象。コピー・選択・再生成・削除はしない |
| 未知file/table・追加checkpoint directory | 正本の可能性があるため拒否 |
| 互換入力338ファイル | 固定許可リストのrepo CSV106・config JSON・既存game_core/phase2_engine Pythonをコピー |

`legacy_backup_compatibility.py` は基点mainで追跡されていた上記338ファイルの固定許可名と集合全体の版SHA。個別SHAは候補内evidenceにだけ保存し、コード/公開サマリーに一覧を載せない。runtimeに任意directoryをglobせず、.env・private token・git設定・tests・backup補助コード・追加ファイルを同梱しない。必須名の欠落、リンク、hardlink、版SHA不一致は拒否する。変更は将来のレビューを伴うコード変更で行う。Windows専用CIはcheckout前にautocrlfを無効にする。

これは**現在インストールされた許可版を同梱する契約**。旧セーブには生成時のCSV/config/コードSHAがなく、当時の外部入力版の一致や他PC完全replayは証明できない。seed・plan fingerprint・resolver・年度登録の正本内照合と、未証明の歴史入力版を区別して表示する。互換性確認のためにload_gameやarchive syncを呼ばない。

## パス・静止・完了の契約

明示的な絶対pathだけを許可し、`..`、祖先/内部symlink・junction、hardlink、special file、原本内mount跨ぎを拒否する。directory entryを調べてから降りるためjunction先を探索しない。Windowsの通常の8.3名はresolveで正規化する。

出力親は既存、出力自身は未存在を要求する。既存の空directoryも拒否する。save rootとの包含・交差、slot alias、実行コード/互換repoとの包含を拒否する。排他的mkdirが同時実行の一方だけを許可し、既存directoryへのrename/replaceは使わない。別volumeの新規独立出力は許可するが、実異種FS転送の保証はしない。

停止宣言に加え、JSON tmpとSQLite WAL/SHM/journalの残存を全走査で拒否する。原本の一覧・SHAを監査前後、copy後、最終境界で比較する。DBは`mode=ro&immutable=1`＋`query_only=ON`で開き、Connection.backupで排他作成済み新規DBへコピーする。WALをimmutableが無視しないよう先に残存artifactを拒否する。全handleをclosingで閉じる。

候補は `payload/<slot>/`、`compatibility/`、privateな`evidence.json`、最後に書く`COMPLETE`。directory自体をステージングとし、公開参照へ切り替えない。標識欠落・途中書込み・digest不一致はverifyで拒否する。失敗候補を削除せず残し、再実行は衝突拒否する。backup上書き・rotation・自動削除はない。

`COMPLETE`は署名なしの完了receiptで、evidenceのdigestを持つ。evidenceの相対名・SHAと原本比較は候補内部だけに置く。保存形式の世代manifest・署名・承認anchorではなく、既存ゲームreaderも参照しない。全evidenceを書換えられる者による偽装は防げない。公開サマリーは件数・一致・容量・時間と固定codeのみで、slot ID・実path・セーブSHA・native例外を出さない。

**停止宣言とファイル監査だけではwriter排他を保証しない。全writerを本当に停止したスロットでだけ利用する。** 共通slot lockは未導入。最後の読取後の変更、TOCTOU/ABA、非参加writer、複数DB同時点、電源断・fsync・NFS・antivirus・別PC再開は保証外。

## 二重検証・障害・測定

`inventory_slot(...authorized_read=True...)`をlegacy_live / legacy_player_historyで使用する。独立`legacy_backup_oracle.py`はproductionのdecoder・ledger helperを使わず、raw SQL/SHAで全schema/行、全年度件数・封印ledger、outcomes出典、全Option A・inning合計、roster/identity、live JSON checksum・試合集合・結果・所属を確認する。元DBと候補の物理page一致を要求せず、原本byte不変と候補論理行一致を別に確認する。

候補validatorは候補内の参照だけを読む。自己生成原本を撤去しても検証でき、現在repoのCSVも読み直さない。固定catalog定数とは比較するが、ゲームload/sync/replay・修復・import・restoreはしない。成功でも`restoration_authorized=false`、`whole_game_restore_proven=false`、`evidence_authenticated=false`。

38テストでENOSPC/EIO/KeyboardInterrupt、backup失敗、receipt失敗、copy間writer commit、最終境界前/成功後の変更、同時実行、WAL実writer、unknown table、seed/plan/ledger/identity改変、旧backup混入、hardlink/symlink/Windows junctionを試す。実disk枯渇や電源断とは区別する。実multi-preview生成も拒否する。ユーザーセーブはテスト入力にしない。

専用Linux/Windows CIは新規38件、Stage91/92/93、年次37回帰、実Tk read-only GUI回帰。Stage89の既存Linux専用19件はLinuxで全assertionを維持する。既存Python CIは全Python3.12 unittestと関東8都県17校E2E。全国100/200年の新規高コスト負荷は追加せず、従来の手動dispatchへ分離を維持する。

6状態（active/sealed/registered×manual/autosave）でcopy＋照合の完了境界までの秒数、source/candidate/compatibility bytesを測る。`observed_source_and_candidate_bytes`は各候補完了時の両集合file合計で、FS割当・Pythonメモリ・既存repo・瞬間的journal・他候補を含む普遍的ピークではない。復元コピーは作らない。全履歴保持と年数無制限を維持し、100年度/索引・32シャード/照会をゲーム年数上限にしない。

次Stageは自己生成fixtureの**新規隔離directory**で検証済み手動restore候補をコピーしread-onlyに照合する実験。元save復元、activation、自動backup/restore、履歴GC、移行、方式B/C、正式GUIは別Stage・別承認。
