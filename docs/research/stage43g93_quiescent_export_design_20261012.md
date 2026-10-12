# Stage43G-93：旧A静止slotの独立export候補（採用前lab）

Issue #241。基点は最新main `a53d7ff1fac06ed50eaf3e2eda4a68083690791b`（PR #240マージ）。[ADR-032](../adr/ADR-032-production-save-inventory-adoption-proposal.md)のA/B/Cはいずれも未採用。本PRのマージも方式Aの製品採用承認を意味しない。

## 実装の入口と所有境界

実装は `tests/stage43g93_fixture_support.py` の `OwnedLab`。コンストラクタには実save rootや出力pathを渡せない。自身で作ったTemporaryDirectory内に、実LiveGameService＋能力モデルの8校・単大会の小規模ゲーム投影を生成する。初期生成後の再利用テンプレートも自分で生成した一時ファイルのみ。全校・全国全大会の実連続進行とは表示しない。

関連する既存年次37回帰のCIでは、`--annual-regressions` が `tests/stage43g93_annual_fixture_runner.py` を使う。native SQLite接続・transaction・既存assertionを変えず、一時fixtureの接続だけを収集して各tearDownの直前に明示closeする。旧fixtureのGC依存でWindowsの一時DB削除が失敗するための実行器であり、製品APIのhandle規約変更や失敗無視ではない。

`phase2_engine.legacy_quiescent_export_audit` はそのunittestを実行するCLIだけであり、製品writer/readerから呼ばれない。引数は新規の監査結果 `--json-output` とfixture回帰の選択だけ。既存slotへのbackup/restore、利用開始、同名復元、migration、GUI、共通slot lock、世代manifest、過去年GCはない。製品コード・schema・保存形式の変更はゼロ。

候補名は短い英数字の識別子に限定。lab内の `candidates/名前` を排他的mkdirで新規作成し、その中の別ディレクトリへコピーする。既存の空ディレクトリも拒否する。祖先・子孫のsymlink/junction/hardlink、path traversal、絶対path、同FS外は拒否。失敗・中断時の途中ディレクトリは利用不可のまま残し、再実行で上書きせず、lab終了時だけ所有一時領域を片付ける。renameで既存slotに公開しない。

これはPython内のテスト所有境界であり、悪意あるPythonコードに対するセキュリティ隔離ではない。利用者実saveを入力するオプションは設けない。

## 正本・派生・互換入力の依存表

[Stage91設計](stage43g91_save_inventory_design_20261012.md)の呼出し調査を引き継ぐ。必要集合は使う経路に依存する。slotの全ファイルが常に存在するという意味ではない。

| 対象 | 分類・依存と本labの扱い |
|---|---|
| manual/autosave JSON | 独立した途中checkpoint正本。明示した一方だけを進行照合対象とし、両系列をbyte不変で保存。latestの自動選択はしない |
| rolling JSON backups | 古いcheckpoint正本候補。checksumを確認して全保持するが、SQLiteと同一時点のbackupとは扱わず、復元対象に自動昇格しない |
| historical_matchesの全年度・全試合 | 最終得点・イニング・team/batter/pitcher成績の永久保持正本。全tableのraw行とschemaを独立比較。既存score-only/byeは欠落情報を捏造しない |
| archive_identity / career_years | seed/resolver/plan、年度登録、封印件数・ledger正本。独立計算のledgerとinventoryを併用。過去年も全保持 |
| historical_competition_outcomes | 前年度資格・ランキングの正本証拠。同じDB内のtable全行を保持。未知tableを派生と推定しない。大会資格を再計算・自動承認しない |
| career_school_rosters / career_player_identities | 学校年度snapshot・永続選手identity正本。payload SHA、所属年度、gradeを除くidentityを独立照合。全保存年度をコピー |
| career_previews / career_multi_previews | 単大会・複数大会の途中replay正本。参加・draw・seed/plan・前年度ledger・rosterに依存。完全依存を本labで証明できないためchecksum/slot診断後も要手動判断で拒否 |
| regional / kanagawa / placement previews | upstream同年checkpoint、feeder、placement、地区推薦・選択の正本。上流の再同期・補完はしない。同じく要手動判断 |
| invitational参加manifest / year_rulebooks | 参加選択・年度host/ルールの正本。既存参加manifestは本Stageで禁止する世代manifestと別物。未検証依存があれば拒否 |
| year_continuity / tokai_preflights | 前年度封印・roster系譜・旧live参照選択・事前凍結planの正本。JSON-only移送では不足。同じく要手動判断 |
| slot_metadata | 表示用。保存時刻を集合の世代証明に使わない。存在すれば保持 |
| derived_player_stats / v2 stats / v2学校索引namespace | 派生。欠落と正本欠落を区別し、既定ではコピーしない。比較試験のみ同梱可能だが解析・選択・承認・再生成をしない。絶対path束縛は移送しても有効化しない |
| 正本DB内B-tree | 同一DBの一部としてbackup。DROP INDEX/VACUUM/migrationはしない |
| 未知file/table | 正本の可能性があるためfail-closed。新しい原本を無断で破棄しない |
| 外部data CSV・config JSON・game_core/phase2_engineのPython | master、学校/地域/名前入力、calendar/qualification/feeder、能力生成・成長・試合設定、resolver/planner/engineの互換依存。fixture生成時の全対象ファイル集合を保守的に一時コピーしprivate pin。欠落・変更・追加で拒否。slotには元来同梱されていない |
| 架空v2 calendar/history | 旧A liveと未接続のG年正本。本labの入力に混在したら未知正本として拒否する。v2を旧A年度進行の証拠にしない |

名前providerのコード・元CSVは上記互換集合に含む。Python/SQLite/OSは監査結果で別に記録し、別OSのreplay同値をbyte SHAから推定しない。外部入力の全履歴版管理・署名・完全互換catalogは将来課題。

## 状態別の判定

| 状態 | 候補作成の条件・限界 |
|---|---|
| 年次進行中 | 明示manual/autosaveの完成試合が当年archiveと完全一致。JSON先行・archive先行はいずれも要手動判断、候補作成停止。roster componentも必須 |
| 封印後 | 当年の全試合と選択checkpointが一致し、件数・ledger・選手identityが正しいこと。古いmanual/backupに戻して封印済み試合を捨てない |
| 隣接翌年登録後 | 前年sealed全履歴＋翌年activeの登録metadataを全保持。実試験は翌年登録まで。翌年度の全大会run、成長・資格・全所属の復元保証ではない |
| career途中進行・参加/feeder証拠あり | checksum/slotと原本欠落は診断するが、完全依存を検証できない場合は必ず要手動判断。実career multi preview生成の拒否回帰も含む |

選んでいない系列・rolling backupsは過去の証拠として保持する。同じseed/plan/bytesの外国slot、整合的な過去の切り落とし、署名なしmemoの世代偽装を内容だけで識別できない。生成時のprivate oracle/pinが必須であり、候補内の偽SHAや `approved=true` は承認根拠にしない。

## 「静止」の条件と読み取り専用証跡

fixture生成writerの全操作が終わり、JSON rotation・archive sync・roster操作が途中でなく、全SQLite handleが閉じた状態を所有者が宣言する。前後file集合・SHAが一致し、WAL/SHM/journal/.tmpが一つもなく、checkpoint/archive年度状態が整合することを要求する。停止宣言がなければ読取前に拒否する。

既存 `save_inventory_audit.inventory_slot` をliveとplayer historyの二契約で再利用。原本は `mode=ro&immutable=1` と `PRAGMA query_only=ON` で開く。immutableで未checkpoint WALを見落とさないため、全残存sidecarを先に拒否する。DBごと `Connection.backup`、非DBは排他的新規fileコピー。source接続の書込み拒否、全handle終了、前後SHA・raw行不変も試験する。

copy後は独立raw SQLで全schema/table/行、payload SHA・key、イニング合計、封印ledger、roster identity、JSON checksum/bytes、互換集合を照合する。DBの物理page配列の一致はbackup契約にせず、元DBのbyte不変と候補の論理内容一致を別に確認する。

非参加writer、外部復元、TOCTOU、ABAに対する排他はない。停止をfile状態だけから証明できない。稼働中liveの無停止export、複数SQLite＋JSONの同時点snapshot、電源断・fsync耐久性・NFS・antivirusは保証外。mtimeで安全判定しない。

## 故障・OS・計測・未保証

途中copyのENOSPC/EIO、DB backup内ENOSPC、KeyboardInterrupt、file衝突、保存途中artifact、リンク/跨ぎpath、既存出力、偽checksum/plan/seed、2slot混在、封印ledger/identity改変、古いJSON、master/config/code欠落、最後の照合後の改変を決定的に注入する。電源断や実disk容量枯渇の再現とは区別する。

Ubuntu/Windows CIでhandle解放・新規作成・同FS renameを検証する。跨ぎFSはst_dev変更の注入で拒否境界を検証し、実異種FS間移送は未検証。Windowsのjunctionとhardlinkも拒否し、8.3短縮名はresolveで正規化。開いたfileへのrenameは契約にせず、全handle終了後だけ試験する。

候補payload bytes、原本slot bytes、互換入力bytes、候補作成＋照合秒数、観測点でのlab全file合計最大値を記録する。最大値には同lab内の既存候補（既存の証拠JSONも含む）が入り、作成中候補の最後に書く証拠JSON、生成テンプレート・Pythonメモリ・FS割当・一瞬のjournalは含めない。普遍的ピーク容量や電源断耐久性の証明ではない。原本のみ/派生ありの差も測る。

ゲーム年数の新上限はない。100年度/32シャードは既存の索引1file/1queryの制限で、保持年数制限ではない。100/200年・3746校の追加負荷は任意であり本Stageでは未実施。

`whole_game_restore_proven=false` / `restoration_authorized=false` / `generation_adopted=false` を全成功候補にも記録。全所属・能力成長・資格・大会run replay、元slotへの復元、別PC再起動を保証しない。方式Aの静止要件と不足をユーザーが確認し、A/B/Cの正式判断は別途行う。
