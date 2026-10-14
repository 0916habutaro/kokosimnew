# Stage43G-105 実装・実測報告（2026-10-15）

Issue #265。Stage104 merge main `c1dc38f445aff1957c8e81a3467d7b75678c154e`から`stage43g105-registered-full-a`を作成。

## 達成した実試合

Stage104自己生成4校80人、3team/60登録枠の正本とRegisteredMatchInputを直接検証し、新独立driverで農林・塩山合同対帝京第三を完走した。固定結果の代用はない。能力snapshotのschool_id、元Player、永久IDは改変しない。新結果は全行に年/大会/試合を持ち、team_idとorigin_school_idを分離する。

|測定|実測|
|---|---|
|入力seed / 能力seed|430104 / 430103|
|結果|農林・塩山合同 8–1 帝京第三（ゲーム内架空試合）|
|イニング/終了|9回、後攻9回裏まで実施|
|実行イベント/打席|79 / 79|
|投球アウト/奪三振|54 / 21|
|得点/打点/相手投手失点|9 / 9 / 9|
|個人元学校|SCH000202、SCH000220、SCH000196を永久IDからSQL正本と照合|

同seedを二度実行しJSON全内容一致。別seed 0/1/430105で契約通過とイベント変化を検査。実行生成seed探索で延長・後攻裏省略・サヨナラを確認。30回同点/打席安全上限は完全結果を作らず例外。入力seed変更・登録外/二重所属・元学校/対戦team取り違え・欠損重複event・スコア/全個人成績カウンタ改ざん・旧schema・writer誤送信を拒否。

確率と投手BF上限式だけを旧MatchSimulatorから利用する新labモデル。進塁は安打塁数固定、失策/野選重みを通常アウトへ加算。犠打/犠飛/盗塁なし、該当成績は0。投手交代時は打順Pを後任に置換し、責任走者を出塁時投手へ帰属。公式ルールの校正済み再現でも旧シミュレーターと同一エンジンでもない。投球球数はモデル外。コールド/タイブレーク/全国大会/翌年開始は未対応。完全Aはこの明示したモデルで全得点・イニング・投打統計を保持する意味。

## 独立検証・隔離

独立event oracleは乱数、driver進塁、driver成績更新を呼ばず、数値塁位置で走者移動と全打撃/投手成績・責任走者を再集計。driver関数を例外に差し替えてもoracleが成立するテストを用意。別途同seed再実行で入力/確率設定SHA・型/順序とイベントを厳密照合する。read-only Tkはteam別スコア/イニングと永久ID/元学校/全投打成績を表示し、検証失敗時は前回結果も全消去する。

新APIは`phase2_engine.registered_match_driver.simulate_registered_full_a`。旧Stage104の`simulate_registered_match`は旧APIとして拒否を維持し、新APIへの暗黙転送はしない。登録previewも結果を捏造しない。旧game_core、既存writer/schema、保存/restore、履歴reader、338catalog、106CSVは変更なし。新結果はメモリと自己所有TemporaryDirectory内のJSON roundtripのみ。実ユーザーのsave利用0、公式2026試合結果との混同なし、複数store原子性保証なし。

## 検証状況

補助Linux Python3.12.14：新headless/旧7版内容verifyの15件がskip 0で成功（約26秒）。旧候補は真の各commitからgit archiveと別Python processで自己生成したもの。内容健全性と現行replay許可/真正性は別判定、既存の拒否境界を維持。Stage104登録回帰11件、旧MatchSimulator回帰19件も成功。

Windows Python3.12の専用CIは新headless15件とnative mapped Tk 1件をskip 0必須にする。全unittest、関東8都県17校E2E、Stage94以降の既存ゲートをPRで実行する。CIの最終実測はPR本文へ追記する。個人Windows PCの目視手操作は未検証。

## 次Stage

新versioned reader/append-only lab storeの未採用仕様は設計書末尾。製品writer接続・既存セーブ移行・本番restoreは対象外。ADR-037/038はProposedのまま。PRは全必須CI成功後も未マージ、auto-merge無効でレビュー待ち。
