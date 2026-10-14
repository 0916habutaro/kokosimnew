# Stage43G-106 隔離append-only完全A保存設計（2026-10-15）

Issue #267。基点はStage105 merge main `2e6fcaaf9e8a95d281214f5103783f744f7f019a`。Windows個人利用の実験であり、本番saveへの採用ではない。Stage104/105登録lab・新型・oracle・driver・Tk、旧HistoricalMatchArchive、CareerRosterArchive、CareerHistoryBrowseModel、Stage105設計/報告とADR-037/038を調査してから境界を決定した。

## 版と正本依存

|保存対象|キー・参照|読取時の独立照合|
|---|---|---|
|元学校ロスター|2026/学校、自己生成seed430103、80永久ID、全snapshot JSON/SHA|PlayerRosterGeneratorの固定recipeから再生成し全bytes相当のcanonical JSONを比較|
|大会登録正本|2026/CMP000041、登録version/recipe、JSON/SHA|Stage104登録recipe、4校SHA・3team各20枠を再構成|
|出場team正本|年/大会/team、label、team SHA|登録正本全件比較、学校namespaceとの衝突拒否|
|構成学校membership|年/大会/team/school|登録正本から再構成。同年大会の学校二重枠をUNIQUEでも拒否|
|登録選手|年/大会/team/player、origin_school、slot、元ロスターSHA、Player JSON|永久IDと元学校snapshot、20枠とslot、二重登録を照合|
|完全A試合|年/大会/match/result version、team1/2、登録SHA、input JSON/SHA、model/seed/config SHA、result JSON/SHA|Stage105厳密decode、独立event oracle、同seed再計算を全件実施|
|学校参加索引|年/大会/match/version/team/school|登録membershipと対戦teamのSQL join集合を独立照合|

旧HistoricalMatchArchiveのschool-keyed Option Aはteam_idと個人成績school_idを対戦学校と扱い、イベントを保存しない。CareerRosterArchiveは元学校・永久ID・年ロスターを既存DBに保持する。CareerHistoryBrowseModelは旧学校履歴と既存v2 sandboxを読む。これらを新team保存先へ接続しない。旧schema/writer、SaveSlotManager、LiveGameService、CareerCompetitionOutcomes、game_core、master CSV、catalogは変更しない。

`identify_result_format`は二重JSONキー・nonfinite・未対応版・無版新payloadを拒否し、旧無版school-keyed Aと`registered_team_full_a_v1`を識別する。旧版は**構造識別のみ**で、真正性・試合の正しさを新oracleで認定しない。既存旧readerでの内容verifyは別経路に維持する。旧→新変換・新→旧writer adapterはない。新readerはdiscriminatorだけで信用せず、固定登録/元学校recipe・seed・確率設定・全統計を検証する。

## writerと所有範囲

`RegisteredFullALabStore`は生存中の自己所有`tempfile.TemporaryDirectory`オブジェクトのみを受ける。path引数を受けず、固定名`registered_full_a_lab.sqlite3`をO_EXCLで作る。既存ファイルは開く前に拒否し、所有DBのinode変更・symlink・owner消滅も拒否する。APIを製品writerへ接続しない。

TemporaryDirectoryの所有者は再起動実験終了まで保持する。readerは別接続/別プロセスでpathを受けるが、`mode=ro`、`query_only=ON`、exact lab schemaを要求する。DDL/migration/recoveryをreaderから実行しない。生成子プロセスの終了後の実験では、保存・close済みSQLiteを親所有のTemporaryDirectoryに証拠としてcopyし、さらに別プロセスと新Tk windowで開く。これはfixture輸送であって製品backup/copyの原子性契約ではない。所有者cleanup後の永久保持を保証しない。

## append-onlyと故障

全8テーブルをSTRICTとし、UPDATE/DELETE拒否triggerを設定する。schema・triggerも読取時にexact照合する。登録正本・学校ロスター・team・membership・選手・完全A本体・派生索引は同一SQLite内でBEGIN IMMEDIATEによる一括transactionに入れる。既存レコードを読取検証した後、新規行だけINSERTする。

同じ `(year, competition_id, match_id, version)` かつ結果/登録/入力/全正本同一はFalseを返すno-op。異seed、異結果、登録SHA/元学校/構成変更を拒否し、元DB bytesを維持する。Stage106はseed430104の固定試合のみを受理する。意図的な別seed結果も今回のwriterへは保存できない。判別済み別versionも自動採用しない。

|故障・状態|挙動|
|---|---|
|INSERT途中・commit直前例外|rollback、元bytes不変、同じowner/storeで再試行|
|競合insert|BEGIN IMMEDIATEで直列化、完全一致なら一方のみ追加|
|busy/exclusive lock|短いtimeoutでsqlite例外、close、ロック解放後に再試行|
|read-only connection|書込拒否、readerは原本bytes不変|
|WAL / DELETE|それぞれで保存・read snapshot・close/rename/reopenを検証|
|dirty-page spill後のプロセス強制終了|hot journalを要するDBはro readerで復旧せず拒否。自己所有fixtureのみ明示的SQLite recovery後に同writerで再試行|
|SQLite破損・未知schema・孤児・登録欠落|結果なしで拒否、修復/上書きしない|
|初期作成が完了しない領域|既存fileの暗黙overwriteなし。別の自己所有領域でやり直す|

保証するのは**1 SQLiteファイル内のtransaction atomicity**だけ。JSON/複数製品DBの原子性は保証しない。SHAと決定論recipeは整合性検証であり真正性署名ではない。OS/ディスク故障耐性・悪意ある実行コード変更への署名保護は対象外。

## readerと検索

各requestは単一read transactionでschema、integrity、FK、全canonical JSON/SHA相当、登録正本、入力、結果、派生索引を検証し、native connectionを必ず明示closeする。新結果はSQLだけを信用しない。Stage105の独立event oracleでscore/inning/team/投打全counter/責任走者を再集計し、別に同seed実行全内容と厳密比較する。正本の余分な行・欠落行も拒否する。空DBの試合集合は空、保存登録がない状態でteam/学校/選手履歴を捏造しない。

team検索は当時のmembership/登録簿と試合/全Aを返す。構成校検索は参加teamとその試合を返し、合同勝利・優勝を構成校単独成績へ転記しない。永久選手検索は80人の元学校所属と実際の出場投打成績を返す。登録だけのベンチ選手の出場履歴は空。校別勝率・順位・歴代leaderboardは提供しない。将来team解散を理由に当時の台帳をDELETEしないが、今回実証するデータは2026固定fixtureだけ。

`RegisteredSavedFullATk`はStage105 native mapped Tkを流用し、保存済みDBを開いてteam→構成校→永久IDのreadonly comboboxと登録表・全イニング・投打statsを表示する。失敗時は前の結果/選択肢/全表を消去する。GUIの描画前にSQLite接続を閉じ、終了・別window再起動・rename/reopenを確認する。CIのnative Tk成功は個人Windows実機の人による手操作を意味しない。

## 互換と非対象

旧Stage94/99/100/101/102/103/104/105の8候補は真の各main commitからgit archiveで独立checkoutを作り、別Pythonプロセスで自己生成exportする。内容verify、原本bytes不変、catalog338入力/106CSV集合とbytesを確認する。現行replay診断と真正性判定を分け、未承認候補のactivation/restoreを行わない。

実ユーザー候補利用0件・実ユーザーsave互換は未検証。秘密path/実ユーザーSHAを公開しない。全国合同一般化、山梨32team31試合の製品進行、2027開始、本番restore/import/migration/GC、配布用EXEは非対象。ADR-037/038/039はProposedのまま。
