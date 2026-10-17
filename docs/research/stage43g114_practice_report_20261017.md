# Stage43G-114 実測報告

Issue #283。起点はPR #282マージcommit `2804a1ab7552d36f58bb839e8f448815f8b77747`。
指定branch `stage43g114-2027-practice-match-history` を使用する。
実在学校masterと架空選手・架空試合の自己所有隔離試験。既存ユーザーsaveは使用していない。

## Linux補助実測

Linux / Python3.12.14 / SQLite3.53.1。
`python tests/stage43g114_audit.py --json-output work/stage114-linux.json` は8件成功、skip0、failure/error0、202.094秒。
正本は `audits/phase2/stage43g114/linux_practice_20261017.json`。

|工程|完了・結果|時間|DB bytes|
|---|---|---:|---:|
|保存2026山梨|全31試合・32team/33school・学校永久ID660/登録640、封印/seed/event/bracket検証|88.035秒|5,124,096|
|保存2027学校年度|33校受理、現役660、進級396/卒業264/新入264、累計identity924|2.718秒|1,310,720|
|保存入力構築・計算・検証|保存JSON直接decode、単独2校、seed430114|2.483秒|—|
|練習試合・履歴・保存/再開の正例全体|0–3、9回、71打席、打者22行/投手6行|14.718秒|217,088|
|別process再読込・再実行|独立oracle一致、同seed一致、RO bytes不変|4.816秒|同上|

学校IDは `SCH000196` と `SCH000197`。保存2026登録で単独teamであること、masterの学校/program/名称を照合した。
2027公式出場資格を確認したという意味ではない。
イニング表・得点・個人成績は実イベントから計算。71打席、投手51アウト、奪三振12、得点/打点/投手失点はいずれも合計3でoracleと一致。
進級者11人・新入生10人に実打席があり、7人は2026/2027両年度に実登場。打者22行には交代時に有効化された未打席行も含む。
旧3年生264人は2027の全校rosterと出場集合に存在しない。

故障/拒否試験は固定された同じ論理1試合を別の自己所有targetで再計算する。
試験回数やoracle再実行回数を、複数の2027大会試合を実施した実績には数えない。
source receiptに所有実体ID/一時パスを結び付けるため、独立fixture/OS間のinput/result digest同値は要件にしない。
同じ保存入力とseedでのbit同値は、親/別processの両方で確認した。

## 保存・互換性・境界

新規versioned practice SQLiteのみへappend-only保存。commit直前例外rollback、commit直後のlost ack冪等、
commit後強制終了→別process再開、commit前強制終了のhot journal拒否、lease競合、hardlink、
symlink（Windowsではjunction）、sidecar、実体差替、schema/索引/個人成績/イベント/seed改ざん拒否を含む。
明示closeとWindows用pin/leaseを使用し、close→rename→reopenを試験する。
Stage105の計算部そのものに変更なし。製品MatchSimulatorとの差分は設計書の走塁/失策/犠打等の表に記載した。

旧Stage113は変更前マージcommitから真に自己生成した旧候補をRO verifyし、catalog338・master106CSV・候補bytes一致に成功。
既存15版のgateは維持し、合わせて旧16版を検証対象とする。旧候補のrestore/replayはしない。
catalog338対象コード、master/data、既存writer/schema/save/backup/履歴は編集していない。
Stage111原本と2027年次sourceは各試験前後のbytes一致。Stage113 sourceを新試合の入力にしない。
roster-only source、未受理2027、異source/年/seed、未知選手/学校は拒否する。

## Windowsと最終CI

Windows Python3.12専用fixtureを既存年度jobの先頭へ追加し、測定JSONを早期artifactとして公開する。
既存Stage111/112/113の順序と回帰は保持し、job/OS行列は増やしていない。
Windows実測と最終headのCI結果は、実行完了後に本節・PR本文へ追記する。
全unittest、関東17校E2E、Stage100–113 native Tk/SQLite/履歴、既存旧版gateも成功確認の対象。

個人Windows PCの目視、サインアウト→再ログイン、PC再起動は未検証。
hosted CIのnative Windows/SQLiteと別process再開を、個人PCのOS再起動実証と呼ばない。
2027公式大会のentry/qualification/日程/順位/合同継続は生成・確定しない。
全必須CI成功後もPRは未マージ・auto-merge無効・レビュー待ちで停止する。
