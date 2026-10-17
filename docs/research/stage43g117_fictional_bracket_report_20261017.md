# Stage43G-117：架空8チーム大会7試合・汎用ブラケット・年度横断履歴 実測報告

Issue #289。起点はPR #288マージ済main `df91f062e51619f65c66f0fb3f42b06e4f8de872`。
指定済み `stage43g117-2027-fictional-eight-team-bracket` を使用した。
実在学校masterに基づく**ゲーム内架空結果**である。2027公式大会の開始・資格・日程・順位を確定するものではない。

## 補助Linuxの確定実測

Python3.12.3／SQLite3.45.1（Stage116の補助Linuxとは別の環境）。
専用auditは16件・skip0・failure/error0、1670.177秒で成功した（親process CPU 1373.547秒）。
実行中のコード12ファイルのSHAは不変だった。全ケース後に、元の2026・年次2027・練習・Stage116 v1の4DBのSHAを照合した。
根拠は [実測JSON](stage43g117_linux_measurement_20261017.json) の code_sha256、test_seconds、measured。
Linuxでの成功をWindows nativeでの検証の代わりにはしない。

|測定|結果|
|---|---|
|不変出典fixtureの生成・受理|263.877秒（CPU 260.630）。保存2026の31試合→2027全33校・660現役・924永久ID→練習1試合→Stage116 v1 2試合|
|7試合の実行・SQL・独立完全A・4stream閲覧|104.154秒（CPU 103.043）。`play_next` 1試合あたり10.8〜13.2秒|
|保存済み7試合の全再監査（`snapshot`）|6.243秒。出典の再検証が支配的|
|7試合の同seed再計算と`event_oracle`の合計|0.198秒。再帰auditをO(N²)で回しても、この部分は無視できる|
|強制終了→別process再開case|239.321秒（子process5回、各24.5〜34.1秒）|
|7試合保存後のDB|1,290,240 bytes。行数：契約1・試合7・進出7・checkpoint7・出場索引151・順位8・受理1|
|最大RSS|約177 MiB（181,564 KiB）|
|4team実経路|43.499秒・3試合|

case別の秒数：要求gate 105.1、rollback／ACK消失 177.9、hot journal 57.4、別seed 70.2、入力・結果改ざん 148.7、
native close→rename 40.1、強制終了再開 271.2、7試合本体 122.9、schema・checkpoint改ざん 159.1、sidecar・link 11.9、
v1回帰＋4team 63.8、勝者依存・スキップ・並べ替え・別物理出典 169.8、純構造3件 0.04、旧116 RO 8.2。

費用の内訳と、検証を減らさない理由：

- 1回の `_prepare` は `dry_run`（保存authorityを内部で再検証）と `saved_authority` の2回の出典検証からなり、約5.6秒かかる。
  1試合あたり約12秒の大半はこの部分で、試合計算と独立oracleは数ミリ秒。
- `play_next` は「事前検証1回＋保存＋保存後の再監査1回」で、Stage116の3回から2回に整理した。各操作で要求本体の `dry_run` を再実行する点は維持している。
- 出典fixtureはclass内で1回だけ作り、15ケースで共有した。原本の全31試合・受理・保存SQLの検証は各操作で省略していない。
- 必須ケースの削減や新規skipはない。

**将来の32team/31試合（実測からの推定であり、実証ではない）**：1試合あたり約12秒×31で約6〜7分。
再監査の再計算部分は31試合でも1秒前後の見込み。DBは試合数にほぼ比例し、約5〜6MBの見込み。
50/100/200年の全試合実証とは呼ばない。

## 明示架空シナリオの実7試合

namespaceは `fictional:stage117-owned-eight`、scenario seedは430117、scopeは `LAB117:2027:FICTIONAL:b9fec4f93067555c`。
単独7（各20人）＋合同1（SCH000202＋SCH000220、10+10人）。9校160人の永久IDはすべて相異なる。
8slot・bye0・宣言シード2つ（team1→先頭、team2→後半の先頭）・資格は全teamが `explicit_scenario`。
以下の日付は宣言した**架空シナリオ日**であり、2027公式日程ではない。

|seq|回戦|架空日|先攻—後攻|得点|回|打席|打撃行|投手行|投手アウト|失点|
|---|---|---|---|---|---|---|---|---|---|---|
|1|1回戦|07-10|team1 帝京第三—team7 SCH000203|2–9|9|80|23|7|51|11|
|2|1回戦|07-10|team4 SCH000199—team8 合同|4–2|9|71|21|5|54|6|
|3|1回戦|07-10|team2 北杜—team6 SCH000201|4–0|9|69|20|4|54|4|
|4|1回戦|07-10|team5 SCH000200—team3 SCH000198|3–1|9|76|22|6|54|4|
|5|準決勝|07-12|team7—team4|1–2|9|72|21|5|51|3|
|6|準決勝|07-12|team2—team5|3–5|9|77|22|6|51|8|
|7|決勝|07-14|team4—team5|3–0|9|76|22|6|54|3|

イニング別得点と全打撃・投手個人成績は、実測JSONの `measured.tournament.games` に保存した。
イベントから打順・塁・アウト・交代・責任投手・全成績を独立に再集計し、別途同seedで再計算して全結果が一致した。
準決勝の4teamは1回戦の勝者だけ、決勝の2teamは準決勝の勝者だけである（独立進出oracleと汎用graphの両方で一致）。
既存2026・2027練習・Stage116の2試合のイベントは転記せず、新しいLAB117 scopeと独立seedで実計算した。

架空scenario内の順位：team4（SCH000199）1位3勝0敗、team5 2位、team2・team7 3位、残り4team 5位。
合同team8は1回戦で0勝1敗（5位）。その結果を構成2校の単独勝敗へ加算せず、SCH000202・SCH000220はともに単独0勝0敗。
Stage116 v1の合同勝敗も単独勝敗に含めない（v1単独0勝0敗）。これらは公式順位・公式合同継続・公式学校勝敗ではない。

4team実経路（SCH000204・205・206＋SCH000207/208合同、bye0、2架空日）も同じ汎用storeで3試合を保存した。
優勝team4（合同）の2勝0敗は、構成2校の単独勝敗に0として現れることを確認した。
純構造試験では3〜32teamの全30通りについて、BYE数、seedのBYE、試合数n−1、graphとoracleの順位一致を検査した。
Stage116 v1の3team配置（seed1にBYE）と同じ配置になることも確認した。

## 保存・再開・拒否・履歴

試合1・4・6・7のcommit直後に、子processを `os._exit(73)` で終了させた。
次の各子processは全出典を再検証してから開始し、その時点の保存試合数は 0→1→4→6、最終の読取で7だった。
- 未完了の段階では優勝null・順位空。
- 試合4の後の次対戦は「試合1勝者×試合2勝者」、試合6の後は「準決勝2勝者」だった。
- 決勝のcommitと同じtransactionで順位8件と最終受理を確認した。
- 再開前に保存した結果のSHAは最終状態の先頭prefixと一致した。
- 親を含む6つの異なるPIDで実行した。2026の31試合・練習1・v1 2試合とRO前後のbytesは不変だった。

次の操作をすべて拒否した：
- rollback、ACK消失後の同一結果再送（bytes不変で `False`）、異結果。
- 敗者の進出、前試合を飛ばした保存・並べ替え、同一IDで異内容の結果。
- 同じ要求・seedで別の物理出典（別AnnualRosterLab）から作った入力。
- 年・seed・日・回戦・scope・元学校・前結果SHA・得点・イニング・打撃・投手の改ざん。
- 本物のprecommit強制終了で残ったhot journal（SQLite接続前に拒否し、DBとjournalを変更しない）。
- sidecar、hardlink、junction、root／DB／leaseの実体差替え、v1とv2のcapability取り違え、lease排他。
- schema・出場索引・checkpoint・順位・受理・進出・契約・sequenceの改ざん、保存2027 rosterの改ざん。

あわせて、SQLite排他lock、全表のappend-only、native handleの明示close→rename→reopenも検査した。

履歴は次の4streamを、year・record_kind・namespace・match_idで分離して扱う。
2026架空大会（31）、2027架空練習（1）、2027 Stage116架空大会（2）、2027今回架空ブラケット（7）。
2026と今回の両方に実打席がある進級者を25人確認した。
進級者・新入生・卒業者のprofileと実投打、scenario内の累計投打、合同entryと元学校・programを区別して閲覧した。
公式2027の参加・資格・合同継続・日程・順位はNone、公式確認・製品開始許可はfalse。

## 旧19版RO・保護対象

旧Stage94/99/100–116の19版について、各main commitから自己生成した候補の内容をverifyした
（今回、Stage116 main `df91f06` のexportを追加した）。新コードで旧版ラベルを付け直していない。
結果は [旧19版実測JSON](stage43g117_old19_linux_20261017.json) に記録した。
catalog338・master106CSV・候補bytesは不変で、restore／replayは非許可。

`git diff df91f06` で、変更・追加の対象が次のとおりであることを確認した。
- 新規の `phase2_engine` 3ファイル
- 新規のtests 4ファイル
- docs
- workflow（path filter・新step・timeout）

Stage111–116の実行コード、製品writer／schema、`data`／`config`／`game_core`、過去のsave／backup／historyへの変更・移行・削除は0。
実ユーザーのsaveは試験入力にしていない。

## CI負荷とtimeout

- Windows年次jobに、16件skip0の専用stepを1つ追加した（新job・新OS行列は追加なし）。
  Stage116時点で、同jobの既存stepはWindowsで約1750秒だった。
  今回の補助Linuxでの1670秒がWindowsで同程度かかると、60分の上限に近づく。そのためtimeoutを90分に延長した（根拠をコメントに記載）。
- 全unittestは、Stage116の2416件／4659.444秒に今回の17件が加わる。95分では余裕がないため、120分に延長した。
- 関東8都県17校E2Eのjobは変更していない。
- 最終headのWindows実測・全unittest・関東E2E・全必須CIの確定値とrun/jobリンクは、PR本文に記録する。

個人Windows PCでの目視・サインアウト／再ログイン・OS再起動は**未検証**。[手動確認手順](stage43g117_windows_manual_20261017.md) を同梱した。
複数DBの一括atomicity・本番復旧・製品全モデルの完全再現・公式情報の認証は主張しない。
全必須CIの成功後も、新PRは未マージ・auto-merge無効のまま、レビュー待ちとする。
