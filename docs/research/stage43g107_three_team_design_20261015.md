# Stage43G-107 3チーム・2試合・隔離保存再開設計（2026-10-15）

Issue #269。PR #268マージ後の最新main `a55b237657ca256e5f516a8dc45f3203afe61917`をGitHubとローカルで照合し、`stage43g-107-three-team-tournament`を作成。Windows専用・個人利用・非配布ゲームの独立labであり、製品writer採用ではない。

## 実コード調査と互換境界

Stage104–106の設計・実測報告とADR-037/038/039、および以下の実装を確認した。Stage106真のmainをgit archiveした独立checkoutから別プロセスで自己生成旧候補をexport・内容verifyし、変更前bytesの照合情報を非公開Temporary領域に確保した。実ユーザー候補は使わない。

|既存コード／制約|維持する境界|Stage107の追加契約|
|---|---|---|
|joint_team_registration_lab.pyのRegisteredMatchInput|LAB104 match1、seed430104、固定登録recipeとstrict型照合を維持|別型TournamentMatchInput。Stage104 validatorへ転送・型偽装しない|
|登録正本・_team_input|4校80永久ID、3team各20登録枠、origin schoolとPlayer不変|登録と能力・打順・投手順の生成だけ再利用。新入力にplan SHA・前試合SHA・試合日を追加|
|registered_full_a_contract.py|registered_team_full_a_v1と全scope／投打／event型を維持|同じ結果型を新しい狭いvalidatorで検証。結果のmatch IDを書換えない|
|registered_match_driver.py|旧公開simulateの入力validatorとrun_seed契約を維持|検証済み新入力から内部_runを明示利用。旧公開入口に新型を通さない|
|registered_full_a_oracle.py|旧公開validatorの固定入力照合と読取時同seed再生成を維持|独立event_oracleを再利用し、新seedの再実行全内容と厳密比較|
|registered_full_a_lab_store.pyの_match|固定match1の再生成・seed430104の保存契約を維持|新しい入力復元はplan＋保存済み初戦勝者から行う。旧_match不使用|
|SQLite immutable 8表・fingerprint|旧store/schema/readerを変更しない|別ファイル・別store版、既存8表のDDLのみ再利用＋plan/進出台帳/team順位の3表|
|registered_saved_full_a_tk.py|既存1試合GUIを変更しない|別Tk・別readerで2試合とteam順位・累計を表示|

338互換catalog入力、106 master CSVとdata全bytes、製品LiveGameService/TournamentEngine/HistoricalMatchArchive/save schema、Stage100–106の旧APIは変更しない。

## 固定planと何が確定するか

登録簿seedと能力seedは430103。学校は農林SCH000202・塩山SCH000220・帝京第三SCH000196・北杜SCH000197。出場枠は学校IDとは別の年大会team ID、LAB104:2026:CMP000041:joint/solo1/solo2。全校は各1枠にのみ参加し、合同は1枠。固定planは登録SHA、3出場枠の順序、BYE、全試合ID・seed・日・対戦出典をcanonical fingerprintへ含める。

|順|試合ID（LAB107:2026:CMP000041:以下）|架空日|試合seed|先攻／後攻|
|---|---|---|---|---|
|1|match1|2026-07-01|430107|農林・塩山合同／帝京第三|
|BYE|実試合なし|開始時確定|乱数なし|北杜が決勝へ進出、勝数を加算しない|
|2|match2|2026-07-02|430108|match1の実計算勝者／北杜|

これは実在の2026山梨県大会の抽選・シード・個別試合日・結果・出場資格再現ではない。新factoryは明示opt_in=Trueと検証済み0/1試合prefixだけを受理する。決勝入力は初戦結果SHAも保持する。初戦の敗者、同team両側、未知試合、別seed、改変plan、同校の重複参加、結果の逆順／重複／欠落を拒否する。優勝者・固定スコアを入力で指定しない。

各試合のevent oracleは乱数やdriverの進塁・集計を使わず、打順・投手交代、責任走者、元学校・永久ID・試合時team、全得点・イニング・team／投打成績を再集計する。別途同seed実行全内容比較を行う。大会oracleはfactory・driver・SQLiteに依存せず、対戦順・勝者の進出・BYE・敗退後再出場拒否・最終3team順位を検証する。

計算モデルはStage105の旧確率と投手BF上限式を部分利用する独立lab。安打塁数固定進塁、四死球押出し、失策／野選の重みは通常アウト、犠打・犠飛・盗塁等は0。9回・裏省略・サヨナラ・同点延長、30回同点と打席上限は結果なし。旧MatchSimulatorと同一ルールでも公式ルールでもない。各試合は同じ能力snapshotから始め、試合間の疲労・怪我は今回モデル化しない。

## 保存・プロセス終了・再開と原子性

OwnedTournamentStoreは生存中の自己所有TemporaryDirectoryだけから新規作成し、固定ファイル名をO_EXCLで確保する。開始時にimmutable登録簿・4校80人の元学校ロスター・3team/60登録枠・plan/BYEを1 transactionで保存。試合0/1/2件の状態を区別する。

親はTemporaryDirectory所有者を保持し、directory/file実体identityを持つ明示的なresume capabilityを生成する。spawn子プロセス1はそのcapabilityで同じ隔離DBを検証し初戦を計算・commit、全native接続close後に終了する。子プロセス2は別プロセス・別接続で保存済み初戦を再検証し、勝者から決勝入力を作り、決勝を計算・commitする。copy／既存saveのrestore／pathからwriterを復元するAPIはない。resume capabilityは信頼された同一fixture内の権限受渡しで、セキュリティ署名や永続的な製品restore許可ではない。親所有者cleanup後の再開は拒否する。

追加時はBEGIN IMMEDIATE内で全旧行を検証し、同一内容ならno-op、異内容なら拒否。完全A・入力・学校参加index・勝者台帳を同じtransactionで追記し、決勝時だけ3team順位も追記する。UPDATE/DELETEは11表すべてtriggerで拒否。readerはexact schema/trigger・integrity/FK・全canonical JSON/SHA・全正本の余分／欠落行・event/seed/大会oracleを毎request検証する。学校参加indexはmembership SQL joinでも独立照合する。

|故障点|可視状態と再試行|
|---|---|
|初戦commit前|試合0、決勝を生成せず停止、初戦から再試行|
|初戦commit後・応答前|試合1、同一初戦appendはno-op|
|決勝計算直前|試合1のまま、決勝計算なし|
|決勝insert途中・commit直前|試合1へrollback、順位なし、決勝再試行|
|決勝commit後・応答前|試合2と順位あり、同一決勝appendはno-op|
|busy・exclusive lock|closeして拒否、ロック解放後再試行。WAL readerはcommit済みprefixのみ表示|
|dirty-page spill後の強制終了|hot journalをRO readerから復旧せずbytes不変で拒否。自己所有fixtureだけ明示的SQLite recovery後、初戦が残ることを照合して再試行|
|欠損・破損・未知schema・実体交換|拒否、修復／上書き／移行なし|

保証は単一SQLite内の**試合ごとの**transaction atomicity。初戦と決勝は別commitであり、大会全体を一度に原子的に保存したとは主張しない。JSON／複数製品DB原子性、OS／媒体故障・真正性署名は対象外。SHAは整合性検証だけである。

## 読取・学校参加・永久選手とGUI

部分snapshotは再開検証用。大会完了読取は2試合と3team順位の両方を要求する。順位は決勝勝者／決勝敗者／初戦敗者。勝敗は実2試合だけからteam単位で算出し、BYEを勝利に数えない。合同勝敗・優勝を農林と塩山の単独勝敗・優勝に転記しない。

学校検索は当時の参加teamとその全試合を返す。永久ID検索は元学校と各試合の実出場投打行、全カウンタの累計を返す。率の和は作らない。登録のみのベンチと合同未選出20人も元学校の80人正本から検索でき、出場・累計は空。全試合・全元学校・全永久IDを保持し、履歴削除・GC・進行年数上限は導入しない。ただし実証は2026の2試合だけで、所有者終了後の保管を製品長期保存と呼ばない。

native Tkは年大会→参加team→試合スコア／全イニング→構成校→永久選手IDをreadonly選択し、チーム順位・BYE台帳・登録簿・全試合別投打成績・累計を表示する。専用tabで表を切り替え、長い成績欄は横スクロールできる。未完了・欠損・読取エラー時は前結果・全表・全選択肢を消去する。表示前にSQLite native handleをclose、終了後にrename/reopenする。正式全国GUIには接続しない。

## 必須受入と止めどころ

新Windows Python3.12 headless gateは22 tests/skip0、native mapped Tkは1 test/skip0を必須化。真のStage94/99/100/101/102/103/104/105/106の9main由来旧候補を別checkout／別プロセスから自己生成して内容verify・原本bytes不変を検証。現行replay許可・真正性・本番restore承認とは別判定。既存Stage94–106の必須ゲートと8校／33校履歴、全unittest、関東8都県17校E2Eを維持する。Linuxは補助、個人Windows PCの人による手操作は未検証。

旧候補suiteの重複は既存stage契約保護のため維持する。将来は9版生成を同一job内で共有する案があるが、共有fixtureの独立性とbytes保持を確認してから別Stageで整理し、既存失敗黙殺やskip追加はしない。公開artifactは集計のみ、秘密・実save内容・絶対path・個別実SHAを含めない。

製品writer/schema統合、既存slot移行・上書き、restore/import/activation、履歴削除、全国一般化、山梨公式32team31試合、2027実開始、配布EXE化は行わない。ADR-037/038/039/040はProposed・製品未採用。実行不可の場合は実件数を報告して停止し、固定結果やvalidator緩和で成功を作らない。PRは最終head全必須CI成功後も未マージ・auto-merge無効でレビュー待ち。
