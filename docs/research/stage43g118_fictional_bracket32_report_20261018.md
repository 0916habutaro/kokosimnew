# Stage43G-118：2027架空32チーム31試合の段階保存・再開・完全A・履歴とCI負荷 実測報告

Issue #291。起点はPR #290マージ後のmain `2cec50ca7818201f702a2512bfdd007a010b5dc8`、
ブランチは `claude/stage-43g-118-save-resume-v9mcpu`。
結果は実在学校masterに基づく**ゲーム内架空結果**であり、2027公式大会の開始・資格・合同継続・日程・シード・組合せ・順位を確定しない。
設計は [設計書](stage43g118_fictional_bracket32_design_20261018.md) を参照。

## 補助Linuxの確定実測

Python 3.13.16／SQLite 3.45.1、4コア（CIのPython 3.12とは別の環境）。
`python tests/stage43g118_audit.py --old-versions --json-output ...` で、専用13件がskip0・failure/error0、1530.170秒で成功した。
続けて旧20版RO（29件）もskip0で成功し、151.007秒だった。
実行中のコード14ファイルのSHAは不変だった。
全ケース後に、元の2026・年次2027・練習・Stage116 v1・Stage117 8teamの5DBのSHAを照合した。
根拠は [実測JSON](stage43g118_linux_measurement_20261018.json) の `measured`・`test_seconds`・`old_versions`。
Linuxでの成功をWindows nativeでの検証の代わりにはしない。hosted Linux／Windowsの値はPR本文に記録する。

|測定|結果|
|---|---|
|共通出典fixture|217.4秒（CPU 214.8）。2026全31試合116.1、2027受理33校3.6、練習1試合7.6、Stage116 v1 2試合24.1、Stage117 8team 7試合51.8、32team store作成3.5|
|32team／31試合（子7process、強制終了6回）|684.7秒。31試合の `play_next` 合計は274.0秒（1試合3.5〜13.7秒）|
|子processの再開（全出典の再検証）|1回あたり14.5〜16.6秒、最大RSS 130〜147 MiB（132,964〜150,292 KiB）|
|16team／15試合（子6process、強制終了5回）|319.6秒。`play_next` 合計は93.0秒|
|31試合DB|5,586,944 bytes（作成時1,077,248。1試合あたり+127〜180 KB、平均145 KB）。4096 B×1364ページ|
|DBの内訳|契約1,022,247 B（作成時DBの約95%）、入力JSON計1,916,512 B、結果JSON計2,290,748 B。行数：契約1・試合31・進出31・checkpoint31・出場索引695・順位32・受理1|
|16team DB|2,707,456 bytes。出場索引335行|
|保存済み31試合の全再監査（`snapshot`）|5.47秒|
|31試合の同seed再計算＋`event_oracle`|0.30秒|
|hot journal（決勝precommit強制終了）|149,040 bytes|

case別の秒数（setUpClassの共通fixtureと実試合を除く）：
16team確認3.9、32team境界確認5.1、完全A＋規模計測22.4、6stream履歴17.7、決勝境界・hot journal 109.7、改ざん13種81.7、
要求拒否13種29.5、v1/v2不変13.7、契約4件0.02、真のStage117 RO 3.9。

### 31試合での費用の内訳とO(N²)

1試合の保存（`play_next`）は「事前検証」「新規計算」「append（旧行と新行の導出）」「保存後の再監査」からなる。
31試合の合計274.0秒の内訳（層別の包含時間）は次のとおり。

|層|31試合の合計|性質|
|---|---|---|
|`_prepare`（出典＋要求の再検証）|190.4秒（うち `dry_run` 85.6・`saved_authority` 84.7）|試合数に依存しない定数×呼出回数。1回約3.3秒、1試合2回（子の最初の1試合だけ1回）|
|`_rows`（保存済み全試合の再導出）|79.0秒|1試合で3〜4回呼ばれ、各回が保存済み試合数Nに比例 → 合計O(N²)。試合1で0.02秒、試合29で6.4秒|
|うち再計算・event oracle|8.2秒＋8.9秒（各1,823回）|1回あたり約5ミリ秒|
|新規試合の計算|0.1秒（31回）|1試合約4ミリ秒|

直接計測した `_rows` の時間は、保存済み1・8・16・24・31試合でそれぞれ0.024・0.224・0.596・1.220・1.789秒だった。
入力連鎖（前結果SHA）は0.001・0.042・0.170・0.393・0.693秒。どちらもNに対して超線形に増える。
31試合では、まだ出典再検証（定数部分）の方が大きい。ただし、終盤の1試合では `_rows` が半分近くを占める（試合29で13.7秒中6.4秒）。
64試合以上や、年度をまたいで同じstoreへ追記する場合には、O(N²)の部分が支配的になる見込みである。
今回は検証を削らず、v2を変更しなかった。次工程の課題として、checkpointに束縛した前結果SHAの再利用と、既検証prefixの差分検証を挙げる。

Stage117の推定（1試合約12秒×31で6〜7分、DB 5〜6MB）に対し、本環境の実測は31試合の計算・保存が274秒（約4.6分）、DBは5.59MBだった。
本環境はStage117の補助Linuxより約2倍速い（Stage117の7試合は1試合10.8〜13.2秒、本環境の序盤は約7秒）。
このため、hosted runnerでは1試合あたりの時間がおよそ2倍になる見込みで扱う。

## 明示架空シナリオの実31試合

namespaceは `fictional:stage118-owned-thirty-two`、scenario seedは430118、scopeは `LAB117:2027:FICTIONAL:c453a5398657cc92`（v2版の規約による接頭辞）。
単独31（各20人）＋合同1（team32＝SCH000202＋SCH000220、10+10人）で、33校・640人の永久IDはすべて相異なる。
32slot・bye0。宣言シードはteam1〜4で、標準位置（先頭・末尾・各半分の端）に置いた。資格は全teamが `explicit_scenario`。
日付は宣言した**架空シナリオ日**であり、2027公式日程ではない。

|seq|回戦|架空日|先攻—後攻|得点|回|打席|打撃行|投手行|投手アウト|失点|
|---|---|---|---|---|---|---|---|---|---|---|
|1|1回戦|07-09|team1(SCH000196)—team26(SCH000223)|1–8|9|81|23|7|51|9|
|2|1回戦|07-09|team16(SCH000212)—team19(SCH000215)|5–3|9|80|22|6|54|8|
|3|1回戦|07-09|team29(SCH000226)—team21(SCH000217)|4–2|11|93|24|8|66|6|
|4|1回戦|07-09|team15(SCH000211)—team28(SCH000225)|1–7|9|76|22|6|51|8|
|5|1回戦|07-09|team4(SCH000199)—team24(SCH000221)|1–2|9|63|21|5|51|3|
|6|1回戦|07-09|team12(SCH000208)—team10(SCH000206)|9–2|9|80|24|8|54|11|
|7|1回戦|07-09|team11(SCH000207)—team9(SCH000205)|5–2|9|74|22|6|54|7|
|8|1回戦|07-09|team27(SCH000224)—team18(SCH000214)|0–3|15|116|26|10|88|3|
|9|1回戦|07-09|team2(SCH000197)—team8(SCH000204)|5–4|9|79|22|6|54|9|
|10|1回戦|07-09|team13(SCH000209)—team14(SCH000210)|5–2|9|80|22|6|54|7|
|11|1回戦|07-09|team25(SCH000222)—team7(SCH000203)|6–0|9|79|23|7|54|6|
|12|1回戦|07-09|team32(合同)—team6(SCH000201)|7–0|9|83|22|6|54|7|
|13|1回戦|07-09|team3(SCH000198)—team23(SCH000219)|3–2|9|81|23|7|54|5|
|14|1回戦|07-09|team30(SCH000227)—team5(SCH000200)|0–2|9|68|21|5|51|2|
|15|1回戦|07-09|team20(SCH000216)—team31(SCH000228)|0–9|9|74|21|5|51|9|
|16|1回戦|07-09|team22(SCH000218)—team17(SCH000213)|7–5|10|93|24|8|60|12|
|17|2回戦|07-11|team26—team16|7–6|9|77|22|6|54|13|
|18|2回戦|07-11|team29—team28|0–3|9|80|22|6|51|3|
|19|2回戦|07-11|team24—team12|4–0|9|74|22|6|54|4|
|20|2回戦|07-11|team11—team18|4–1|9|76|22|6|54|5|
|21|2回戦|07-11|team2—team13|2–3|9|65|21|5|51|5|
|22|2回戦|07-11|team25—team32(合同)|1–2|9|74|22|6|51|3|
|23|2回戦|07-11|team3—team5|5–2|9|74|22|6|54|7|
|24|2回戦|07-11|team31—team22|8–2|9|80|22|6|54|10|
|25|準々決勝|07-13|team26—team28|6–1|9|83|23|7|54|7|
|26|準々決勝|07-13|team24—team11|2–3|9|75|22|6|51|5|
|27|準々決勝|07-13|team13—team32(合同)|4–5|9|81|22|6|51|9|
|28|準々決勝|07-13|team3—team31|6–4|10|92|23|7|60|10|
|29|準決勝|07-15|team26—team11|7–1|9|80|23|7|54|8|
|30|準決勝|07-15|team32(合同)—team3|7–0|9|85|23|7|54|7|
|31|決勝|07-17|team26—team32(合同)|4–2|9|83|22|6|54|6|

31試合で計214得点・2,479打席だった。延長は4試合（試合3＝11回、8＝15回、16・28＝10回）。
イニング別得点と全打撃・投手個人成績は、実測JSONの `measured.thirty_two.games` に保存した。
親processは保存済み31試合のすべてについて、次の照合を行った。
- イベントからの独立再集計（打順・塁・アウト・交代・責任投手・全成績）と、同seedでの再計算が一致する。
- 前結果SHAの連鎖が切れていない。
- 汎用graphと独立進出oracleの順位が一致する。
- 各ラウンドの参加teamが前ラウンドの勝者だけである。
- 出場索引695行が、イベントの打者・投手とentry teamの集合に一致する。
- 全32teamの実打者に、2026からの進級者と2027新入生がいる。

Stage117の7試合・2026の31試合・練習・v1のイベントは転記していない。

架空scenario内の順位：
- 1位：team26（SCH000223）、5勝0敗。
- 2位：合同team32、4勝1敗。
- 3位：team11（SCH000207）とteam3（SCH000198）。
- 5位：4team、9位：8team、17位：16team。

合同team32の4勝1敗は、構成2校の単独勝敗に加算していない。SCH000202・SCH000220は全scenarioで単独0勝0敗である。
これらは公式順位・公式合同継続・公式学校勝敗ではない。

16team（`fictional:stage118-owned-sixteen`、seed 430218）は、単独15＋同じ合同1（17校・320人）で15試合を行った。
優勝はteam5（SCH000200）で4勝0敗、合同team16は1回戦で敗退した。

## 段階保存・強制終了・別process再開

- 32team：試合1・16・24・28・30・31のcommit直後に、子processを `os._exit(73)` で終了させた。
  次の各子processは全出典を再検証してから開始し、その時点の保存試合数は0→1→16→24→28→30で、最終の読取で31だった。
  PIDは親を含めて8個で、すべて相異なる。
- 各子processの次の対戦は、保存済み結果から汎用graphで導いた「前の実勝者」の組と一致した。
  例：試合16の後は「試合1勝者team26×試合2勝者team16」。
- 境界ごとに保存した各DB bytesは、試合数＝checkpoint数で、決勝前は順位0件・受理0件だった。
  決勝のcommitと同じtransactionで、順位32件と最終受理1件が入った。
- 再開前の結果SHAは最終状態の先頭prefixと一致した。最終の子processは6stream履歴を構成した。保存2026・練習・v1・Stage117のbytesは不変だった。
- 16team：試合1・8・12・14・15で同様に確認した（0→1→8→12→14、最終15）。順位は1・2・3・3・5×4・9×8。

選ばなかった境界：残りの中間試合を個別に強制終了するケースは置いていない。
選んだ境界はすべてのラウンド境界（16＝1回戦完了、24、28、30、31＝決勝）と最初の保存を通る。
子1回の追加費用は出典再検証の約15秒＋その試合の保存で、1試合ごとに強制終了すると31試合で約8分増えるため、今回は増やさない。

決勝境界（30試合時点の保存bytesを新しい自己所有storeへ書き込み、全再監査を通してから実施）：
- commit前rollbackでbytes不変、順位0件。
- commit後のACK消失では、DBに31試合・順位32・受理1が入った。同一の再送は `False` でbytes不変、異seedの結果は拒否した。完了後の `play_next` も拒否した。
- 決勝の本物のprecommit強制終了（子process）では、149,040 bytesのhot journalが残った。SQLite接続前に拒否し、DBとjournalは変更しない。

31試合DBの改ざん13種を、RO監査でbytesを変えずに拒否した。
- 未知の表。
- 出場索引の追加・削除・entry付替え・Stage117の行の混入。
- 試合SHAの書換え、順位を残したままの決勝行削除。
- checkpointの書換え。
- 順位の変更・削除、受理の削除、進出の付替え、契約内の架空日の変更。

要求の拒否13種：卒業者、他校選手、合同11+9、entry ID重複、合同構成校の単独二重参加、合同宣言の欠落、BYE数、64枠、4日付、2026年、official namespace、「公式」ラベル、seed17。
同じ要求で別の物理AnnualRosterLabを出典にした場合も拒否した。いずれも1件あたり1.4〜3.4秒（要求gateが先に止めるもの）。

複数SQLite間の一括atomicity・本番復旧・電源断耐久性は主張しない。

## 年度横断履歴

`fictional_scenario_history.scenario_history` は6stream・87試合を扱い、match_idに重複はない。
各streamは `(year, record_kind, namespace)` で分離する。

|年|record_kind|namespace|試合|
|---|---|---|---|
|2026|fictional_tournament|CMP000041|31|
|2027|fictional_practice|LAB114:PRACTICE|1|
|2027|fictional_tournament|fictional:stage115-owned-demo|2|
|2027|fictional_bracket_tournament|fictional:stage118-owned-thirty-two|31|
|2027|fictional_bracket_tournament|fictional:stage117-owned-eight|7|
|2027|fictional_bracket_tournament|fictional:stage118-owned-sixteen|15|

構築に17.3秒かかった（3storeそれぞれの出典再検証と全再監査を含む）。
- SCH000202・SCH000220は、全scenarioで単独0勝0敗。合同記録はscenarioごとに別に持つ：32team 4勝1敗、8team 0勝1敗、16team 0勝1敗。
- 32teamと8teamの両方に単独で出たSCH000196は、scenarioごとに別entryの記録を持つ。全scenarioの単独勝敗は、各scenarioの単独entryだけの合計になる。
- 2026と今回32teamの両方で実打席がある進級者は123人だった。
- 永久IDごとに次を閲覧できる：6streamの状態（在籍／未入学／卒業）、profile、entry team付きの出場、scenario別の投打累計。
  新入生の2026は未入学、卒業者の2027の5streamは卒業で出場なし。
- 公式2027の参加・資格・合同継続・日程・順位・結果はNone、公式確認・製品開始許可はfalse。
  正式 `HistoricalMatchArchive`／`CareerCompetitionOutcomes`・製品セーブ・masterへは書き込まない。

## 旧20版RO・保護対象

旧Stage94/99/100–117の20版について、各main commitから自己生成した候補の内容をverifyした。
今回、真のStage117 main `2cec50c` のexportを加えた。
旧20版の実測は、補助Linuxで29試験・skip0・failure/error0、151.0秒だった。
catalog338・master106CSV・候補bytesは不変で、restore／replayは非許可。

Stage116 v1・Stage117 v2（ブラケット・oracle・store）・Stage115 gate・Stage114練習・Stage111年次・driver・oracleの10ファイルは、
`git show 2cec50c:<file>` とbytes一致を試験で確認した（`test_08`）。
変更・追加したもの：
- 新規 `phase2_engine/fictional_scenario_history.py`（読取専用）。
- tests 6ファイル（新規）。
- docs。
- 新workflow 1つ。
- 既存6workflowのpath filter 2行ずつ。

製品writer／schema、`data`／`config`／`game_core`、過去のsave／backup／historyへの変更・移行・削除は0。実ユーザーのsaveは試験入力にしていない。

## CI負荷と設計

- 実規模ケース（`tests/stage43g118_scale_cases.py`）は `unittest discover` の既定patternに入らない。
  新workflow `stage118-fictional-bracket32.yml` の専用job（ubuntu／windowsの2行列、check 2件追加）だけで実行する。
  既存のWindows年次job（main実測約65分44秒／上限90分）と全unittest（約77分10秒／上限120分）には直列追加しない。
  このため、両jobの時間はStage118で実質的に増えない。全unittestに増えるのは高速契約4件（0.02秒）と真のStage117 RO 1件（約4〜8秒）だけである。
- 契約テストは、専用workflowの存在・両OS・`--old-versions`・実規模ファイルの名前（`test_` で始まらないこと）を検査する。
  配線が消えると全unittestが失敗する。
- 専用jobのtimeoutはLinux 90分・Windows 120分とした。根拠：本環境で実規模1530秒＋旧20版151秒（約28分）。hosted runnerは約2倍遅い見込み（Stage117比）で、Linux約56分の見込み。Windowsは実測で確定する。
- 追加のrunner時間は1push（PR）あたり2job分。確定値はPR本文に記録する。
- 既存のcheck・timeout・skip条件は変更していない。

個人Windows PCでの目視・サインアウト／再ログイン・OS再起動は**未検証**。[手動確認手順](stage43g118_windows_manual_20261018.md) を同梱した。
50／100／200年の実行、全歴史Aの索引・検索・容量監査（Stage119候補）、実ゲーム進行／read-only GUIへの接続（Stage120候補）は対象外。
本Stageの成功を「全国シーズン完成」「無制限年数の実証」「製品統合済み」とは呼ばない。

## 次工程の課題

- v2の `_rows` は保存済み全試合を毎操作で導出し直すため、O(N²)である。31試合では許容範囲だが、試合数・年数が増えると支配的になる。
  前結果SHA・結果SHAのcheckpoint再利用と既検証prefixの差分検証を、新版（v3）として設計・独立検証する。v2の読取互換は維持する。
- 契約JSONが32teamで約1.0MBになり、DBの約2割を占める（全team入力を含むため）。多数scenarioや長期履歴では、team入力の内容アドレス化を検討する。
- `scenario_history` はstoreごとに出典を再検証するため、構築時間がstore数に比例する（3storeで17秒）。Stage119の全歴史A索引では、検証済みreceiptの共有を検討する。
