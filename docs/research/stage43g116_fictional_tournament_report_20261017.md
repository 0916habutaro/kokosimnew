# Stage43G-116：架空3チーム大会2試合・再開・年度横断履歴 実測報告

Issue #287。起点はPR #286マージ済main `8dd971c55fca0562f7137aeab293bd6db033064e`。
指定済み `stage43g116-2027-fictional-three-team-tournament` を使用した。
実在学校masterに基づく**ゲーム内架空結果**であり、2027公式大会の開始・資格・日程・順位の確定ではない。

## 補助Linuxの確定実測

Python3.12.14／SQLite3.53.1。専用auditは13件・skip0・failure/error0、571.998秒で成功。
実行中のコード8ファイルはSHA不変。全ケース後に元2026・年次2027・練習試合DBのSHAを照合した。
根拠は [実測JSON](stage43g116_linux_measurement_20261017.json) のcode_sha256、test_seconds、measured。
Linux成功をWindows native検証の代わりにはしない。

|測定|結果|
|---|---|
|不変出典fixture生成・受理|115.474秒。2026保存31試合→2027全33校・660現役・924永久ID→保存練習1試合|
|2試合実行・SQL／独立完全A／年度横断閲覧case|28.897秒。target作成はcase別時間にも記録|
|強制終了・別process再開case|75.391秒。保存1試合→未完了確認→試合2保存→さらに別process RO照合|
|全2試合保存DB|471,040 bytes。別の自己所有一時DB、製品slot未使用|
|進級・卒業・新入|396進級／264卒業／264新入。SQL保存profileを直接比較、新入IDを独立SHA recipeで確認|
|永久ID年度横断実打席|2026と今回2027の両方に実打席がある進級者10人を確認|

出典はclass内で一度生成し、12ケース間で不変のまま共有した。原本の全31試合・受理・保存SQL検証は
各操作で省略していない。新CI job追加0、既存年次jobに1step追加。ケース削減や新skipはない。
生成時間／各case時間／原本3DB SHA／コードSHAを分け、未計測の速度改善率は主張しない。

## 明示架空シナリオの実2試合

namespace=`fictional:stage115-owned-demo`、scenario seed=430116。
scope=`LAB116:2027:FICTIONAL:54ce3c946f6d4489`。
単独20＋単独20＋合同10+10、合計60登録。4枠・bye1・実2試合。
以下の日付は宣言した**架空シナリオ日**であり、2027公式実日程ではない。

|試合ID末尾|架空日|先攻—後攻|得点|回|打席イベント|打撃行|投手行|
|---|---|---|---|---|---|---|---|
|match1|2027-07-01|山梨農林＋塩山の明示合同—北杜|8–9|10|110|26|10|
|match2|2027-07-03|北杜—帝京第三（BYE）|5–6|10|89|23|7|

独立oracleの投手アウト数は各58、得点＝RBI＝投手失点はそれぞれ17／11。
イニング別得点と全打撃・投手個人成績は実測JSONのgames内に保存した。
イベントから打順／塁／アウト／交代／責任投手／全成績を独立再集計し、別途同seed再計算と全結果一致。
Stage114の0–3を再演せず、新しいLAB116 scopeと独立seedで実計算した。

架空scenario内の順位は帝京第三1位（1勝0敗）、北杜2位（1勝1敗）、合同3位（0勝1敗）。
BYEは勝利に数えない。合同の0勝1敗を各学校の単独勝敗へ加算せず、両校とも単独0勝0敗。
独立seed430119では合同が3–2で実勝利し、その場合も構成2校の単独勝敗0を確認した。
これらは公式順位・公式合同継続・公式学校勝敗ではない。

## 保存・再開・拒否・履歴

1試合commit直後に子processを `os._exit(73)` で終了した。
別PIDの読取ではmatches=1／complete=false／champion=null／ranks=[]。
次processが勝者だけを決勝へ進めて試合2を実計算・保存し、その次の読取で2試合・架空優勝・順位を確認。
前試合の結果SHAが再開後も一致し、2026の31試合・2027練習1件・RO前後bytesは不変だった。

各試合の保存直前例外rollback、保存後ACK消失と同一結果再送、異結果・敗者進出・前試合欠落・
別seed／日／年／scope／元学校／入力digest／得点／イニング／打撃／投手改ざんを拒否した。
本物のprecommit強制終了で残ったhot journalは、SQLite接続前に拒否し、DBとjournalを変更していない。
sidecar、hardlink、junction、root／DB／lease実体差替、lease排他、SQLite排他lock、全表append-only、
schema／索引／結果／受理改ざん、native handle明示close→rename→reopenを検査した。

履歴は2026架空大会／2027架空練習／2027今回架空大会をyear・kind・namespace・match_idで分離。
進級者・新入生・卒業者のprofileと実投打、合同entryと元学校／programを区別して閲覧した。
公式2027参加・資格・合同継続・日程・順位はNone、公式確認・製品開始許可はfalse。

## 真の旧18版RO・保護対象

[旧18版実測JSON](stage43g116_old18_linux_20261017.json)：27試験・skip0・failure/error0、141.962秒。
旧Stage94/99/100/101/102/103/104/105/106/107/108/109/110/111/112/113/114/115の
main commitから自己生成した候補を内容verifyした。新コードで旧版ラベルを付け直していない。
catalog338・master106CSV・候補bytesは不変、restore／replayは非許可。
既存製品writer/schema、master、過去save/backup/historyへの変更・移行・削除は0。
実ユーザーsaveを試験入力にしていない。

## Windows・全unittest・関東E2Eの一次証拠

Windows専用実測は、この変更のPRのChecksにある既存workflow
`Stage43G-111 Windows annual roster lineage and cross-prefecture contract` のartifact
`stage43g111-windows-annual-rosters` 内 `fictional-tournament2027.json` を一次証拠とする。
専用13件skip0を強制し、既存111–115の件数／skip条件・native SQLite/Tk回帰・旧版検査を維持する。
WindowsとLinuxのコードSHAを照合し、結果の所有fixture間SHA同値は要求しない。
**最終headのWindows実測・全unittest・関東8都県17校E2E・全必須CIの確定値とrun/jobリンクは、同PR本文へ記録する。**
これにより補助Linux実測とWindows証拠を分け、検証後の文書追記だけで長時間CIを再起動する負荷を避ける。
検証中のcheckは成功扱いにしない。

個人Windows PCの目視・サインアウト／再ログイン・OS再起動は未検証。
[手動確認手順](stage43g116_windows_manual_20261017.md) を同梱した。
複数DBの一括atomicity・本番復旧・製品全モデル完全再現・公式情報認証は主張しない。
全必須CI成功後も新PRは未マージ・auto-merge無効・レビュー待ちにする。
