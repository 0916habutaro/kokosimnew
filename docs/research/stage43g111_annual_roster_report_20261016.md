# Stage43G-111 年次継承の実測報告

## 結果と範囲

最新main `b3d2e31ef90bc2924f576e3d69c44044a050a218`から専用ブランチで実装した。
保存済み2026ゲーム内大会の31完全A・全seed再実行・独立event/bracket oracle・32team最終順位/台帳・33校660永久IDをRO検証した後、保存学校ロスター正本を入力に既存`advance_school_roster` / `CareerRosterArchive.advance_and_save`を再利用する。
2027学校ロスターの別隔離SQLite保存と、学校・選手の2026/2027年度別RO閲覧を用意した。

|項目|独立SQL/JSON/SHAで確認した値|
|---|---:|
|2026学校/学校台帳選手|33校/660人|
|2026大会team/登録枠/保存試合|32/640/31|
|卒業/進級/新入生|264/396/264人|
|2027学校/現役|33校/660人|
|2027各校の1年/2年/3年|8/5/7人|
|残した永久identity（卒業生含む）|924人|
|2027試合・大会登録・日程の新規生成|0|

2026のDB/metadata/marker bytesは前後不変。2027の読取と確定後再試行もDB bytes不変。
元学校・入学年・氏名・守備位置・利き手・roster_noを含む全フィールドを進級前後で比較し、学年だけ+1と確認した。
新入生IDは卒業枠と既存のhash契約から独立に計算して照合した。氏名が同じ仮選手も永久IDで区別する。
農林・塩山は学校ロスターを別々に継承し、2026合同teamの順位・勝敗を単独校へ複写しない。
未登録20人、卒業264人、新入264人を含め、924人の2026/2027状態と試合別/通算を確認した。

## Linux補助実測

Python3.12.14 / Linux。同時に全unittest・関東E2Eを実行した環境での補助測定であり、Windows個人PCの性能値ではない。
[集計JSON](../../audits/phase2/stage43g111/linux_annual_rosters_20261016.json)に公開可能な計数だけを保存した。

|測定対象|秒|保存bytes|
|---|---:|---:|
|自己生成2026の31試合・0/1/16/30拒否検証を含む準備|152.607664|5,124,096|
|初期2026を別領域へ保存済みの状態から33校継承・全体確定|1.967780|1,310,720|
|隔離ロスター単独1校・200回進級（2026〜2226）|0.422959|2,412,544|
|追加年次7試験＋真のStage110旧候補1試験|264.925|—|

8件成功・skip0。初期化・各負例・別process起動時間を含むsuite合計を、33校継承だけの時間と混同しない。
200年ロスター単独は201 snapshot・1355永久identity・毎年現役20人を保持し、生成試合0・ゲーム年度受理0。最古選手の履歴が残り、索引から最大3校年を読む既存player_historyを確認した。

## 故障・再開・保存境界

正常prefixの1校保存後に親のSQLite/lease/pinを完全closeし、別Pythonを起動した。
次の校のcommit直後にprocessを`os._exit(73)`で終了し、さらに別processで33校完了・年度受理・閲覧まで進め、同じ924identityと確定後bytes不変再試行を確認した。
年度確定前のmapping/acceptance transactionで例外を入れた場合は両方rollbackし、33校分が存在しても未確定のまま閲覧拒否する。
確定commit後のACK喪失は確定済みのまま同一bytesで再試行できる。
実SQLite hot journalを残すprocess強制終了では、再開時にSQLite接続を開く前に拒否し、journalもDBも修復・削除しないことを確認した。

0/1/16/30件、marker空白/重複key、schema追加、SHAを再計算した異seed、保存ロスター元学校改ざん、順位欠損、別demo capability、年次学校欠損、恒久identity改ざん、部分mapping/偽確定、異seed、新入ID衝突、sidecar/hardlink、競合OS lease/SQLite lock、2028等の範囲外参照を拒否する。
native接続を保持する観測fixtureで操作後のcloseを確認し、DB rename→戻し→RO再開も成功した。
故障注入時の書換え/リセットは今回新しく自己生成した使い捨てfixtureだけであり、実ユーザーや既存Stage110の保存物へ行っていない。

## 互換性と必須CIの証跡

Stage110 mainのコードから`git archive`で別checkoutを作り、別Pythonで模擬旧候補を生成してRO内容verifyした。338catalog入力・106master CSVを含む全data bytesが同じで、候補bytes不変、旧候補コードを実行しないことを確認した。
既存Stage109/110の12版gateを変更せず、真のStage110を追加して旧13版とする。古いcatalogが一致しない版へのreplay許可は与えない。
製品writerと既存実装コードは変更せず、新規年次モジュール/例/試験/資料/専用workflowを追加した。
既存Stage91〜96保存境界CIの発火pathに新年次モジュール/試験を追加し、Stage110までの回帰gateも最終headで発火するようにした。各gateの内容・件数・skip条件は変えていない。

Windows Python3.12の新headless年次gateは8件/skip0を要求し、自己生成実31試合、年次継承、独立照合、SQLite close/rename、process再開と故障拒否を実行する。
年次Tkは追加していない。既存Stage109/110のWindows native mapped Tk、save/restart/全660人履歴・Stage100〜110回帰、全unittest、関東8都県17校E2Eの必須CIはそのまま実行する。
**最終headのWindows実測・全CIのrun/job結果、全unittest件数とskip、関東E2Eの結果は本PR本文に記録する。** 先行Linux測定を最終Windows成功の代わりに扱わない。未完了の検査を成功とは記載しない。
Linux補助の全unittestは2,363件成功（skip57）・2,375.915秒、関東8都県17校E2Eは2件成功・422.722秒。既存skipを増やしていない。
Windows新gateの集計は`stage43g111-windows-annual-rosters` artifactとCIログに保存する。DB、capability、private metadata、実ユーザーのSHA/pathを公開artifactへ含めない。

Stage111ではsourceの31試合fixtureを年次試験クラス内で1回だけ共有し、故障ターゲットは独立所有とした。
既存必須suiteのfixtureや検証をskip/cache化していない。将来共用するならOS/Python/正確なsource commit/catalogごとの生成時間・hit/missを比較し、各利用時の全内容verifyと独立fault所有を維持する案を別レビューする。
今回の主な準備時間は2026保存writerが各段階で全検証する処理であり、継承1.97秒だけからCI全体の短縮率は算出しない。

## 未検証事項と停止条件

本人Windows PCの手操作、目視、サインアウト→再ログイン・PC再起動後のStage110再開/実体IDは**手動未検証**。
Windows runnerでの自動TkやPython process再起動はOSログインsession再起動の実証ではない。
実ユーザーの既存デモ/save/backup使用0件・変更0件で、その実データ互換性を検証したとは主張しない。
[手動追記](stage43g111_windows_manual_20261016.md)を用意し、旧Stage110シートも維持した。

成功は2027の学校年ロスター継承までで、2027大会プレイ可能を意味しない。
2027日程・公式出場資格・合同継続/登録構成は未確定。大会試合、2027本番slot、正式全国GUI接続、既存saveの変更/移行/復元、履歴削除、EXE/配布を行わない。
最終headの全必須CIが成功してもPRは**未マージ・auto-merge無効・レビュー待ち**で停止する。
