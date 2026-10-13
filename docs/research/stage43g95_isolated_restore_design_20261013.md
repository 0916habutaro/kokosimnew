# Stage43G-95：自己生成候補の隔離複製と読取検証

Issue #245。PR #244を含む最新main `80409dab2d9c3fbfb861c8e909c9d730454abb5a`から独立ブランチを作成した。[Stage94設計](stage43g94_manual_backup_design_20261012.md)、[報告](stage43g94_manual_backup_report_20261012.md)、[ADR-033](../adr/ADR-033-manual-independent-backup-adoption.md)をコードと照合した。採用判断は変更しない。本実験は本番restoreの採用ではない。

## 入口・生成・信頼境界

実装はすべて `tests/stage43g95_*` と専用テストに置く。CLI `python tests/stage43g95_audit.py --json-output <新規報告JSON>` は外部save/candidate/復元先を受け取らない。Fixtureが自分のTemporaryDirectoryで作った旧Aスロットだけを使う。生成はStage94の実LiveGameServiceと能力試合resolverでnew_game→advance/play→manual/autosave保存→archive sync、封印・outcomes記録、隣接翌年register_next_yearを実行する8校単大会。active/sealed/registeredとmanual/autosaveの6状態を測る。

生成直後・export前の元SHA集合、独立raw SQL全schema/全行、SQL読み取り専用閲覧結果、現在repoの固定互換入力338ファイルのSHAをprivateなメモリに保持する。製品Stage94 export_backupで候補を生成しverify_candidateを実行する。その後、元の全非DB原byte、全DB論理行、互換入力集合/byteを独立比較して初めて候補全体のSHAをprivateに固定する。SQLite backupで物理page配置が変わることがあるため、元DBと候補DBは論理一致、候補と隔離先はbyte一致を要求する。

候補のevidence/COMPLETEは期待値の出典にしない。private anchorが未知・不一致なら `untrusted_needs_manual_review` で拒否する。source_filesを書き換えてreceiptも再計算した候補、および2027の封印済み空年度・2028登録を整合的に削った候補について、製品の内部検証は通ってもprivate anchor照合は拒否することを試験する。これら追加年度は実API登録/封印であり、2027/2028の実試合進行・全再開は主張しない。2026の全試合とoutcomesを含む全年度が比較対象となる。

## 隔離出力・完了境界

出力はFixture自身の一時root直下の新規directoryに限定する。元save領域、候補、repoとの包含/交差、相対path/..、symlink/junction/hardlink、WAL/SHM/journal/tmpを拒否する。既存空directoryも拒否し、排他的mkdir・各fileのxb作成で二重実行の一方だけを許可する。既存slot登録・activationや製品GUI/CLIのrestore入口は新設しない。

先にCOMPLETE以外をコピーし、全ファイル集合/SHA・SQL・閲覧・元候補不変を照合する。最後にCOMPLETEをコピーし再検証する。通常例外/KeyboardInterrupt後は自分が書いた隔離先の完了receiptだけを取り除き、途中データは保持する。履歴や原本・候補を削除しない。実子プロセスのos._exitによる途中終了でもCOMPLETE未作成を確認する。再実行は途中directoryへの衝突として拒否する。成功後も毎回private anchorとの照合が必要で、COMPLETE単独による承認はない。

コピー中writerの故障注入では攻撃側が候補を書き換えるため、候補SHAの変化を期待し、ハーネスの書戻しがないことと元fixture不変を別々に確認する。他の失敗は故障注入後の開始時から元/候補が不変。これを「writerが改変した候補も不変」と混同しない。

## 独立SQLと読み取り専用閲覧

legacy_backup_oracleは製品decoderを期待値に使わず、integrity_check、schema、全table全行を比較する。全年度試合の最終得点、inning合計、全個人成績、年度台帳/封印、outcomes出典、roster/player identityと所属、選択live JSONの結果を確認する。非選択系列とrolling backupsは全file原byte比較で保持する。

追加のbrowseは `mode=ro&immutable=1` と `query_only=ON`、closingでSQLite接続を閉じる。全年度一覧、全試合の個別payload、全学校の試合一覧、全学校年度roster、全player identityを正本から読む。list_yearsがexecutescriptする既存archive readerは呼ばない。load_game/sync/replay/修復は隔離先でも実行しない。試合閲覧には全inning/team/batter/pitcher payloadが含まれる。架空v2 G年sidecarは旧Aと区別しStage94が拒否する。派生学校索引はコピーせず絶対path束縛を利用しない。

## 故障とOS検証

専用20テストで6状態、欠落、JSON/rolling/互換入力改変、checksum/ledger/roster/identity/outcomes/unknown table、unknown版/metadata/slot/source/path、整合的証拠偽造と年度切落とし、既存空/非空/再実行/包含/外部path、WAL/SHM/journal/tmp、hardlink/symlink/Windows junction、ENOSPC/EIO/KeyboardInterrupt、実プロセス途中終了、先行receipt、後置receipt書込み失敗/直後改変、コピー中候補変更、完了後改変、同時実行を確認する。

fixture-isolated-relocation.ymlはUbuntu/Windows Python3.12で新規20、Stage94の38、Stage91/92/93、年次37、Tk読取15を実行する。Stage89の既存Linux専用19もLinuxで維持する。checkout前にautocrlfを無効にし互換入力byteを保持する。DB handle解放は直後renameで検証する。全Pythonと関東8都県17校E2Eは既存python-tests.ymlを維持する。大規模100/200年測定は追加せず従来の手動jobに分離する。

## 保証の範囲

実測は各fixtureの元/候補/隔離先file bytesとexport・隔離copy＋照合時間。全同時候補・FS割当・瞬間journal・メモリを含むピークではない。固定互換入力は現在許可版で、保存生成当時の外部入力版や他PC完全replayを証明しない。

unsigned evidenceを全て偽造できる攻撃者を排除したとは主張しない。private anchorは当該プロセス内の自己生成fixture用で、署名/鍵/永続承認anchorではない。最終観測後の変更、TOCTOU/ABA、電源断/fsync/NFS、複数DBの同時点原子性、真のwriter排他、途中career/他PCの全ゲーム再開は保証外。全ゲーム再開証明・本番復元承認は常にfalse。

自動backup/restore、本番restore API/CLI、save root内復元、slot切替、GUI組込み、共通lock、世代manifest、schema/形式移行、履歴GC/削除は実装しない。100年度/1索引・32シャード/1照会は照会上限であり、ゲーム年数上限を新設しない。PRは全CI成功後も未マージ・auto-merge無効でレビュー待ちにする。
