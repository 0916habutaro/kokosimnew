# Stage43G-106 実装・実測報告（2026-10-15）

Issue #267。Stage105 merge main `2e6fcaaf9e8a95d281214f5103783f744f7f019a`から専用ブランチ`stage43g106-isolated-full-a-store`を作成。新規lab module・専用Tk・検証・文書・Windows CIで完結し、製品save/writer/schema/旧履歴には変更なし。

## 保存・終了・再起動の実証

固定seed430104でStage105の独立driverを実際に実行し、農林・塩山合同 8–1 帝京第三の架空9回1試合を専用SQLiteへ保存した。4校80永久選手の元学校ロスターsnapshot、3team各20登録枠、構成学校membership、登録正本・入力と各SHA、model/seed/確率設定、score/全inning/team/投打stats、隔離event証拠、学校参加索引を保持する。

生成writerのnative接続をcloseした後、別Pythonプロセスで原本をmode=roで読込。また別の生成子プロセスが保存したDBを親所有TemporaryDirectoryへ証拠copyして終了し、第三プロセス・別接続・新Tk windowで再読込した。raw SQL/JSON/SHA、membership SQL join、元学校永久ID、独立event oracle、同seed再実行が一致。SQL結果だけを信用していない。

|実測|値|
|---|---|
|架空試合|8–1、9回、seed430104|
|event/打席|79 / 79|
|投球アウト/奪三振|54 / 21|
|全得点/打点/相手投手失点|9 / 9 / 9|
|専用SQLite bytes（DELETE、1試合/全正本）|311,296|
|保存時間（Linux補助）|0.592383秒|
|検証読取時間（Linux補助、oracle/reexecution込み）|0.315600秒|
|headless・旧8版検証|22 tests、skip 0、126.288秒、成功|
|補助mapped Tk|1 test、skip 0、8.810秒、成功|

Linux Python3.12.14の時間は全unittest/関東E2Eとの同時実行下で測定した値で、Windows性能・長期scaleの保証ではない。Windows Python3.12の専用CIは22件とnative mapped Tk1件をskip 0必須とし、DBサイズ/保存/検証読取時間をartifactへ記録する。最終CIの実測・全チェック一覧はPR本文に記録する。

## 拒否・冪等・復旧

同一完全結果の再保存は追加なし、DB bytes不変。異seed、score、入力SHA、登録SHA、学校構成、二重選手登録を拒否。INSERT競合は別接続で直列化して一方のみ追加する。全8tableのUPDATE/DELETEはtriggerでも拒否。各table追加後とcommit直前の故障注入でrollback・元bytes不変・同writerで安全な再試行を確認した。

DELETE/WAL、exclusive lock/busy、mode=roの書込拒否、native handleを保持したままclose確認→rename/reopenを検証。dirty-page spill後に子プロセスを強制終了してhot journalを残し、ro readerが原本/sidecarを変更せず拒否することを確認。自己所有fixtureだけを明示的にSQLite recoveryし、元bytesへ戻った後に同じowner/writerで再試行する。readerから修復やmigrationを行わない。

JSON二重キー・再SHA後のscore/seed/version改変・元学校ロスター改変・登録欠落・孤児・学校索引欠落・未知schema/SQLite破損・unknown team/player/year/competitionを拒否。新形式は旧readerへの変換なし。旧無版Aの構造識別は新oracleによる旧試合認定ではなく、旧形式の内容verifyは既存専用経路を使う。SHAは真正性署名ではない。

## 検索・Tk

teamは当時の登録簿/構成校と試合完全Aを参照する。農林/塩山のどちらからも同じ合同teamの同一試合へ到達し、合同勝利を各校単独勝敗・優勝へ二重計上しない。永久ID検索は元学校所属と実出場投打statsを返し、ベンチの出場履歴は空。学校順位/勝率/歴代集計は未提供。

保存済みreadonly Tkはteam→構成校→永久IDを選び、当時20枠と元学校・score/全inning/全投打statsを表示する。unknown試合・破損DBでは前の全表示/選択肢を消去。終了・別window再起動・DB bytes不変とnative close/rename/reopenを検証した。Linux補助の初回はsandboxの表示ソケット接続で失敗し、Xvfbへ接続できる実行環境で成功した。個人Windows実機で人が操作したとの主張はしない。

## 互換保護・限界

Stage94/99/100/101/102/103/104/105の8候補を真の各main checkoutと別Pythonプロセスから自己生成exportし、read-only内容verify/bytes不変を確認。Stage105の338catalog入力と106CSVの集合/bytes不変。古いcatalog不一致候補の現行replay拒否を維持し、一致する候補もこのStageで新しいrestore/activation承認を与えない。既存Stage100–105回帰・全unittest・関東8都県17校E2Eの最終結果はPRで確認する。

実ユーザーsave/候補利用0件、実ユーザーsave互換未検証。データは2026固定小規模fixtureのみ。TemporaryDirectory所有者のcleanupで領域は消えるため製品長期保管の完成ではない。単一SQLite transaction原子性のみで、JSON/複数製品DB原子性・本番save統合・自動migration/restore/import・全国合同・32team31試合進行・翌年開始・真正性署名・全打席の製品無期限保存は実装しない。ADR-037/038/039はProposed。

PRは必須CI成功確認後も未マージ、auto-merge無効のレビュー待ちで停止する。
