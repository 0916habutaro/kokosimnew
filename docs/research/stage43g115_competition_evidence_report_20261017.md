# Stage43G-115 実測・保護確認報告

2026-10-17。対象は自己生成・自己所有の隔離fixtureのみ。
設計は `stage43g115_competition_evidence_design_20261017.md`。
2027公式情報の確認とCI成功を混同しない。

## 実行対象

保存2026山梨31試合→保存2027全33校受理（660現役／永久ID924）と、
別DBの2027架空練習試合1を準備し、3team（単独2、明示合同1）の独立dry-runを検証する。
登録、資格、免除、合同二重所属、地区版、seed、draw枠／bye、日程宣言の正例・拒否を区別する。
新規2027大会試合／順位／公式カレンダー生成は0件。
公式entry・合同継続・資格・seed・地区版・日程は未確定のまま。

## 補助Linux計測

Python3.12.14。以下はhosted Windowsとは別の結果で、同時実行の負荷を含む。

|検査|実測結果|
|---|---|
|旧94/99/100/101/102、103–113の計16版RO互換性|13試験成功、skip0、85.367秒|
|追加する真の旧114候補RO内容verify|1試験成功、skip0、4.167秒|
|catalog／master／候補|338入力・106CSV bytes一致、候補bytes不変、restore/replayなし|
|新規Stage115独立ゲート監査|`tests/stage43g115_audit.py` の測定JSONとPR最終Checksに記録|
|関東8都県17校E2E|PR最終Checksの独立jobで確認|

## Windows専用CIと全回帰

既存Windows年次roster workflowに新規Stage115 CLIを追加。
12試験・skip0・failure/error0を必須とし、native Windows以外ならCLI自体が拒否する。
`competition-evidence2027.json` にOS／Python／SQLite、全体秒数、fixture準備秒数、
正例検査秒数、独立gate結果、公式未確定理由、生成0件、旧版追加数を保存する。
JSONには自己所有fixtureのidentityに束縛されたdigestがあり、公式出典の認証値ではない。
CIのartifact `stage43g111-windows-annual-rosters` に既存111/112/113と合わせ保存する。

既存114保存SQL→実練習試合→別process再開の8件、111の8件、112の10件、113の10件と、
既存100–114 native Tk／SQLite／保存・履歴・冪等性／拒否／hot journalゲートを維持。
旧114を加え旧94/99/100/101/102/103/104/105/106/107/108/109/110/111/112/113/114の17版。
新規ゲート変更でも既存6個のsave安全性workflowが起動するようpathsを追加し、監査を省略しない。

全unittestは既存skip条件を変更しない。前段114の4489.878秒／75分枠終了時cancel実測を受け、
新規保存31fixtureと拒否検査分を見込み95分枠にする。関東17校E2Eは独立30分枠を維持。
成功の確定値・run URL・最終headはPR本文の最終検証欄とChecksを参照する。
本書を追加した時点の進行中CIを成功扱いしない。

## 不変性と制限

全新規case後に元31試合DB／marker／namespace・学校年DB・練習試合DBのSHA一致を確認。
新規正例では338入力とmaster全ファイルbytesも照合。製品writer/schemaと既存saveは変更しない。
各dry-runは保存証拠を再監査する。一度得たboolを次の呼出しのauthorityに流用しない。
新規case群は1組の不変fixtureを共有し、31試合をcaseごとに独立生成しない。
破壊・crashを行う既存fixtureとの共有は避け、監査対象・件数・既存skipを減らさない。

ユーザー既存saveを読み込んだ互換性保証ではなく、真の過去commitによる自己生成候補のRO検証。
個人Windows PCのGUI目視・サインアウト→再ログイン・PC再起動は未検証。
全国GUI／47県シーズン／2027公式実データ推測登録／本番restore・migration／配布物は対象外。
全必須CI成功後もPR未マージ・auto-merge無効・レビュー待ちで停止する。
