# Stage43G-96：隔離作業スロットの実再ロード・決定論的続行監査

Issue #247。最新main `8cdb88676f1a78e3c93fe67ee3fe92b9df01a2c6`（PR #246）から専用ブランチを作成した。通常gitのproxy接続が利用できなかったためGitHubコネクタで差分・commit情報を取得し、8追加ファイルから構成したtreeがmainのtreeと一致し、署名を含むcommit objectのSHAもmainと完全一致することを確認して分岐した。

## 読み直した契約と実依存

[Stage91](stage43g91_save_inventory_design_20261012.md)、[Stage92設計](stage43g92_legacy_concurrency_design_20261012.md)・[報告](stage43g92_legacy_concurrency_report_20261012.md)、[Stage93設計](stage43g93_quiescent_export_design_20261012.md)・[報告](stage43g93_quiescent_export_report_20261012.md)、[Stage94設計](stage43g94_manual_backup_design_20261012.md)・[報告](stage43g94_manual_backup_report_20261012.md)、[Stage95設計](stage43g95_isolated_restore_design_20261013.md)・[報告](stage43g95_isolated_restore_report_20261013.md)、[ADR-033](../adr/ADR-033-manual-independent-backup-adoption.md)を実装と照合した。製品契約・採用範囲を変えない。

`LiveGameService.load_game` → `SaveSlotManager.inspect/load` → `read_live_season_save/restore_live_season_save`はseed/yearからplannerを再構築し、保存processed_datesを実engineでreplayする。完成試合全payload・status/activation・public snapshot fingerprint・runtime summaryを照合し、historyを復元する。その後`_sync_history`がDBへ書く。syncはschema確認とBEGIN IMMEDIATEを伴うため、読取専用候補にloadを使えない。JSON保存→metadata→履歴syncは別公開であり、複数DBとJSONをまとめた原子性はない。`finalize_season`はmanual保存・同期・件数確認・封印で、翌年ゲームを開始しない。

`save_slots`はrootとslot IDから保存先を決める。live JSON自体にslot IDはない。fixtureの`owned94` identityとarchive出典を保存したまま、baseline-work/owned94とisolated-work/owned94という別rootに新規directoryを作る。元のsave rootに登録・切替しない。work用serviceではmax_backups=0とし、既存rolling JSONをrotation/削除せず全byteを保持する。時計metadataだけ両系列同じfixture時計に固定し、ゲームseed・試合日時には介入しない。

`HistoricalMatchArchive.sync`は既存試合の同一性、年度identityと封印を検証する。`CareerCompetitionOutcomes.record_completed`は封印年度ledgerとMAIN試合SHAを出典に持つ。`CareerRosterArchive.save_initial_roster`は初年度snapshotを恒久identityと保存し、既存snapshotへの同一再保存は冪等。初年度resolverは保存生成時と同じAbilityMatchResolver、同じteam generation seed・能力/match configを使う。resolverは実試合からroster cacheを作り、試合後の保存済みroster・全個人成績所属を独立SQLで照合する。cacheを製品の恒久能力正本と主張しない。fixture専用owned_sqlite_handlesで接続を終了し、Windows cleanup/renameを可能にする。製品writerはpatchしない。

## 信頼・コピー・再ロードの順序

入力はStage94 Fixtureが自己生成したTemporaryDirectory内の8校単大会旧Aのみ。Stage95 Experimentが生成直後の元file SHA・全table/schema/行・閲覧payloadと338互換入力をメモリに固定し、製品export/verify、独立SQLと非DB原byte照合、隔離コピー・read-only照合を行う。receiptを期待値の出典にしない。

その後Stage96は元・候補・隔離証拠のprivate anchor、候補verify、独立facts/browseを再確認する。明示manual/autosaveがexport選択と一致すること、生成時互換版を自己生成過程で知っていること、現在repoの固定catalog、2026・seed・8校plan fingerprintを確認する。生成当時の版不明を現在catalogが一致するだけで許可しない。これは当該process内の自己生成出典限定の判定で、外部saveの真正性ではない。

root名と所有TemporaryDirectoryの関係、絶対path・親・symlink/junction・既存directoryを確認し、排他的mkdirとxbコピーで新規workを作る。baselineは元fixtureから、isolatedは読取証拠のpayloadから複製する。コピーbyte、全SQL、全閲覧payload一致後にprivate work pinを固定し、再ロード直前も再照合する。未確認・欠落・改変・不整合はload前に拒否する。故障で途中workが残っても上書き再実行しない。完了標識による自動activationはない。

各系列はfresh engineでloadし、MatchSimulator.simulateの実呼出し数とcheckpoint完成試合数が一致して0でないことを確認する。create_live_season_saveで復元後全checkpointを元JSONに一致させ、初期全SQLも不変と確認する。activeは年末まで残り1試合を実行し、封印・outcomes・roster・manual/autosaveを保存する。sealed/registeredは保存済み2026を7試合replayして安全な封印境界を再確認する。登録済み2027は実ゲームcheckpointが無く、2027へのadvanceは明示ValueErrorを要求する。登録を翌年進行成功と数えない。

最終全table/schema/行、全試合payload（勝敗、日程、score、inning/team/batter/pitcher）、全年度roster/選手identity、年度台帳/封印SHA、outcomes、両checkpoint JSON、public runtime/draw/progressionとyear-end readinessを両系列で厳密比較する。2回のsyncで全SQLとwork SHA不変、さらにfresh engineで最終7試合をreplayした再ロードでも同一性を確認する。初回6状態だけを測定行とし、故障テストが行数を増やさない。

DB物理pageの元/候補一致は要求しない。読取証拠→workの初期copyはbyte一致、続行後baseline/isolatedは独立SQL論理一致を要求する。元・候補・隔離証拠の全file集合/SHAは成功前後・通常故障前後で一致する。攻撃注入で保護入力を変えたケースは注入後の開始時からハーネスが書き戻さないことを確認し、攻撃自体の変化を無かったことにしない。

## 故障・実行・報告

専用20テストで6状態×2系列、原本/候補/読取証拠改変・receipt/互換/メモリ証拠欠落、catalog違い・生成時外部版不明・plan/seed/slot混在、manual/autosave取り違え、history ahead、封印/未封印台帳・outcomes/過年度roster欠落、career checkpoint群・feeder/資格/rulebook・v2混在を確認する。work pinのみに依存せず、意図的にworkを再anchorした異常も独立SQL/製品inspectで拒否する。

ENOSPC/EIO/KeyboardInterruptのcopy故障、copy内容破損、既存空/非空/途中work、包含・外部出力、late writer、WAL/SHM/journal/tmp、hardlink、Linux symlink/Windows junction、実BEGIN EXCLUSIVEによるbusy、実read-only writer接続、非決定的resolver、load interrupt、JSON tmp公開I/O失敗、子processの実replay後os._exitを確認する。load以降の例外はworkだけに閉じ込め、保護入力全byte不変を確認する。故障後のworkを自動修復しない。

専用fixture-isolated-continuation.ymlはUbuntu/Windows Python3.12、Stage96、Stage95の20、Stage94の38、Stage91/92/93、年次37、実Tk読取15、既存Stage89 Linux専用19を検証する。既存python-tests.ymlは全unittestと関東8都県17校E2Eを実行する。autocrlfをcheckout前に無効化して互換byteを維持する。各OSの状態・試合・fail-close数・時間・容量をartifact JSONに残し、固定性能閾値を設けない。

CSV106の集合/byteを独立private SHAで前後比較する。既存saveは毎回探索して存在件数を記録し、0件なら既存4件は未検証とする。実saveを入力にしない。公開証跡は件数・真偽・時間・容量のみで、元path/SHA一覧は掲載しない。

## 未保証と次判断

本番restore/import/activation API/CLI、自動backup/restore、save root復元、既存slot上書き、正式GUI、schema migration、方式B/C、共通lock、世代manifest、履歴削除は追加しない。restore承認・全ゲーム再開証明はfalseのまま。既存receiptの真正性や過年度完全性をreceipt単独で保証しない。

今回の保証は自己生成・既知互換入力の8校単大会の2026再ロードと1試合続行、封印/登録後2026閲覧・年次境界である。全国100/200年連続進行、全career、別PC、生成時未知版、実電源断/Windows実稼働rename/NFS、各DB間原子性、真のwriter排他、TOCTOU/ABAは未保証。旧A ISOと架空v2 G年は混用しない。100年度/1索引・32シャード/照会は検索制限でありゲーム年数上限ではない。[ADR-034 Proposed](../adr/ADR-034-fixture-replay-production-restore-boundary.md)に将来製品復元の出典・互換証拠の選択肢だけを記録し採用しない。PRは全CI成功後も未マージ・auto-merge無効でレビュー待ちとする。
