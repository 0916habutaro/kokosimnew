# Stage43G-99 SQLite接続寿命と旧方式A候補の互換判定設計

Windows専用・個人利用・非配布の高校野球ゲームを対象とする。開始点はPR #252をマージしたmain `37f39378af7e8cb5ff27c36cbaeb559d0ad05a58`。Stage98の[GUI設計](stage43g98_windows_gui_design_20261014.md)と自己生成2026年8校単大会の制限を維持する。年度上限、保存スキーマ、完全Option A履歴は変更しない。

## 先に確定した境界

`with sqlite3.connect(...) as conn` は正常時commit、例外時rollbackを行うが、native connectionをcloseしない。接続参照や例外のtracebackを保持するとGCによる解放を待つことになる。Windowsでは使用中DBのrenameが失敗する。DBが使われている間の無停止copyの安全性は、この調査から導けない。

旧方式Aの`verify_candidate`は候補内のevidence／COMPLETE、JSON checksum、SQL原本・ロスター所属・全履歴、338ファイルの集合とdigestを調べる。候補内Pythonを実行しない。現行コードとの一致も、生成時の実コード真正性も保証しない。固定digestはレビューしたbytesの集合を識別するための値であり、署名ではない。

変更前mainをGit履歴から私的一時checkoutへ展開し、別PythonプロセスでStage94の自己生成停止済み模擬セーブをexportした。候補を保持してから製品寿命コードを変更し、変更後のverify／互換診断を実行する。現行候補の証拠を旧版と名乗らせる方法は使わない。旧338ファイルを新しい製品依存として同梱しない。既存のexportが互換ソースを候補へコピーする動作自体は維持する。

## 実呼び出しと所有境界

|経路|生成・返却と寿命|正常／例外・rollback・今回の範囲|
|---|---|---|
|`HistoricalMatchArchive._connect/_connection`|raw connectionの生成者。既存`_connection`がcommit/rollback後finally close。登録・sync・sealはこの経路。match／年度一覧の短期readは既存closing|製品変更なし。同一プロセスのnew/save/load/seal、解放後renameを回帰。生の`_connect`を直接使う外部呼出側は所有責任を持つ|
|`CareerRosterArchive`保存／年度進行|`_connection`を追加。既存と同じ内外transactionの順序でclose。DDL後の全ロスター・identity挿入は既存の内側transaction|**製品変更**。正常・冪等・競合・途中挿入後例外・schema例外・transaction終了例外を検証。例外後に新年度行／identityの部分保存なし|
|同archiveの`roster/school_years/player_history`|値／listを返す。rosterと年度一覧をclosing化、player_historyは元からclosing|**製品変更は前二者**。複数readの値が返却後にも使えること、例外frame保持時に接続が閉じていることを確認|
|`CareerCompetitionOutcomes`|archiveの既存`_connection`を借りる。結果保存とprevious_resultsの生`_connect`利用を置換|**製品変更**。既存DDL／seal確認／結果SHA／transactionを維持。冪等保存、未封印・未知年・schema例外後の解放。保存の本番facade自動統合は対象外|
|`CareerHistoryBrowseModel`|年度・年別試合・試合詳細・選択年選手一覧の4短期connect。fetchall/fetchoneで値を切り離す|**製品変更**。closingだけ追加。SQL・ページ・返却値不変|
|`CareerLongitudinalReadModel`|school_player_indexは短期値返却。`_iter_school_games`は接続を持つprivate generator|**製品変更**。両connectをclosing。school_resultsがgeneratorもclosingで所有。反復中の整合性例外でclose。generatorの利用者は完走または明示closeが必要|
|`CareerPlayerRecordView`|identity一覧は短期connection、`_iterate`と集計は上記generatorを消費|**製品変更**。identity connection、内外generatorの所有をclosingで明示。返却するpublic APIは通常のdict/listのまま。集計途中例外を回帰|
|`CareerHistorySlotSession`→bridge→cross-era read-model|slot/session/bridgeはパス・モデル・ナビゲーション値を保持。原本gate、年度・学校catalog、多くのreadは既存closing。今回のロスター／選手経路も使用|session/bridge変更なし。実Tkの年度→学校→試合→選手、戻る、外部slot拒否、例外・子窓終了後に同一プロセス内で解放を検証。全履歴系APIの普遍的保証ではない|
|`LiveGameService`→`SaveSlotManager`|JSONとarchiveを二段で保存し、loadもarchive syncを書き得る。service/sessionは値を保持し、archiveの短期操作を呼ぶ|両ファイル変更なし。new/save/manual・autosave load/sealを同一プロセスで検証。二段保存のatomic化や自動修復は追加しない|
|Stage98 `demo_read_handles`／writer worker|demo読取の全connectを捕捉しfinallyでclose。writerは操作ごとの子プロセス終了で解放|試験用補助を維持。製品修正の証明には使わない。Stage99の実Tk履歴試験では補助を使わず、製品がcloseした後にassert／renameする|
|未改修のcache／その他SQLite API|`CareerPlayerStatCache`の一部connect、`BrowseRepository`等にwith-only経路が残る。初期化途中例外も個別調査が必要|全面変更しない。今回の5ファイル以外を修正済みとしない。継続判断は[ADR-035](../adr/ADR-035-sqlite-lifetime-and-backup-replay.md)|

Connectionを観測するテストは参照を保持するだけで、検証前にcloseしない。接続の`SELECT 1`がProgrammingErrorになることと、同じ参照を保持したままDB rename→戻す→integrity_checkが通ることを確認し、その後だけfixture cleanupを行う。例外もlistに保持してtraceback由来の寿命を検証する。

## 338ファイルの判定表

ファイル集合338件は不変。旧版`stage43g94-main-2854ee7-v1`のaggregate digestは保持。現行版を`stage43g99-explicit-lifetime-v1`として固定した。差分は上表の5ファイルだけで、残り333ファイルとdata内106 CSVの集合／bytesは変更前mainと独立比較する。個別ファイルSHA一覧や私的pathは公開しない。

|候補|候補内容のverify|導入済み338との診断|現行コードのreplay承認|
|---|---|---|---|
|旧版、候補内338・原本・receiptが一致|受理・read-only。旧版aggregate digestを使用|`installed_catalog_match=false`、`catalog_mismatch_refused`|常にfalse。旧版からの自動再開／移行なし|
|現行版、候補内と導入済み338が一致|受理・read-only|`installed_catalog_match=true`、`separate_replay_review_required`|常にfalse。一致だけではruntime・生成時出典・歴史全体の入力を証明しない|
|既知の健全候補、導入済み338が未知／変更|候補単体verifyは引き続き可能|`installed_catalog_unrecognized`|false。健全な候補を破棄しない|
|未知candidate/catalog版、版名だけ差替え、欠損／改ざん／未完成|拒否。COMPLETE再計算だけでは版固有digestを通過しない|成功扱いを返さない|false|
|診断中に候補変更|`candidate_changed_during_verification`で拒否|成功扱いを返さない|false|

`VERIFIED_CATALOG_DIGESTS`は**候補内容の検証用リスト**。replayの許可リストではない。`verify_candidate`の既存結果キーとread-only契約は維持する。新API `diagnose_candidate_compatibility`／CLI `manual_save_backup compatibility --candidate <絶対path>` が二つの性質を分けて返す。CLI exit 0は内容診断が完了した意味であり、`current_code_replay_allowed=false`を上書きするものではない。exportは現行固定版だけで、未知の導入済みbytesは従来どおり拒否する。候補内Pythonをimport／subprocess実行する入口や、restore先引数はない。

## 段階導入とロールバック

1. 変更前の真のexport候補を生成・保持して、旧338・receipt・SQL検証を固定する。
2. 版固有digestで内容検証を分け、現行環境とのread-only診断を追加する。
3. 所有境界が明確な5ファイルだけをclose改修する。SQL、スキーマ、resolver／ゲーム判定、保存IDは維持する。
4. Windowsのnative handlesとmapped Tkを主要CIで検証し、Stage94–98、全unittest、関東17校E2Eの回帰を通す。
5. PRは全CI成功後も未マージ・auto-mergeなしでレビュー待ちにする。

コードを戻す場合は5ファイルと版・診断の変更を一組で戻し、旧カタログの一致を再確認する。新旧候補は削除・上書き・版名再編集をしない。旧コードが新候補を未知版として拒否するのは安全な制約であり、手動で承認に変えない。既存saveの移行・上書き・履歴削除、本番restore、方式B/C、本番GUI全面実装は行わない。

## Windows受入

Python3.12の専用CIは、実際の変更前checkoutによる旧export＋製品同一プロセス寿命13件と、native mapped履歴Tk 1件を別ジョブで実行する。zero skipsと件数をgateにする。既存Stage98のnew→進行→保存→GUI終了→再構築→manual/autosave再開と、Stage97の実プロセス再起動も維持する。使用中SQLiteのrename拒否はWindowsでのみ必須のassertを実行する。停止済み候補への既存destination export拒否も回帰する。使用中DBを無停止copyできるという主張はしない。

WindowsのCI自動操作と人による個人PCでの目視・操作は分ける。後者は未検証。Linux/Xvfbは補助。既存saveは件数だけ数え、内容を開かず、試験入力に使用しない。公開JSONは件数・環境・結果だけとし、候補本体・旧コード・evidence・原本SHA/path一覧をartifactへ載せない。
