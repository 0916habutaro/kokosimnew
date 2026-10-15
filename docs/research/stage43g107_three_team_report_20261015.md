# Stage43G-107 実装・実測報告（2026-10-15）

Issue #269。最新main `a55b237657ca256e5f516a8dc45f3203afe61917`から専用ブランチ`stage43g-107-three-team-tournament`で実装。[設計書](stage43g107_three_team_design_20261015.md)と[ADR-040](../adr/ADR-040-three-team-owned-tournament-lab.md)参照。既存Stage104–106ファイル・製品save/writer/schema・dataは変更していない。

## 実際に計算した2試合

Stage104の自己生成4校80永久ID／3team60登録枠を再利用し、北杜にBYEを1つ与えた。新しいLAB107 match1/match2と別seedでStage105独立lab driverの内部計算を実行した。勝者は計算結果から決まり、スコア・勝者の書換えはない。

|項目|初戦|決勝|
|---|---|---|
|対戦|農林・塩山合同／帝京第三|初戦勝者の農林・塩山合同／北杜|
|seed／能力seed|430107／430103|430108／430103|
|架空スコア|8–2|7–3|
|イニング|9|9|
|event／打席|92／92|81／81|
|投球アウト／奪三振|54／19|54／13|
|得点／打点／相手投手失点|10／10／10|10／10／10|

ゲーム内の架空試合であり、実際の2026公式大会の試合結果・抽選・日程の再現ではない。計算は旧MatchSimulatorの確率と投手BF上限式の部分利用、進塁は確定塁数、失策・盗塁・犠打等なしの独立labモデルで、旧製品と同一ルールではない。個人元学校、試合時team、永久ID、打順・投手交代と責任走者、全イニング・team/投打カウンタを独立event oracleと同seed全再実行で検証した。

最終順位は1位農林・塩山合同（2勝0敗）、2位北杜（0勝1敗・BYEは勝数外）、3位帝京第三（0勝1敗）。合同優勝を農林・塩山それぞれの単独優勝へ転記しない。学校検索は当時の参加teamとその試合、永久ID検索は各試合の出場投打行と全カウンタ累計を返す。4校80人全員を照合し、ベンチ・合同未選出の選手の出場成績は空とした。

## 隔離保存・実プロセス終了と再開

親が自己所有TemporaryDirectoryを保持して開始登録とplanをcommitし、そのstoreがmintした実体identity capabilityをspawn子1へ渡した。子1は初戦を計算・保存・closeして終了。子2は同じSQLiteを別プロセスでRO検証後、初戦勝者を決勝入力にして計算・保存した。保存済み結果のcopyや本番restoreは使わない。子のPIDが親と異なること・終了コード・各段階の0/1/2試合を確認。親所有者が消えたcapabilityは再開できない。

SQL/JSON/SHAと登録membership join・永久ID/元学校・plan/BYE/勝者進出台帳・順位を検証し、同一再追記はno-op。異seed・勝者・前試合SHA・敗者決勝入力・学校出典・欠損登録・再SHA済みBYE/結果改ざんを拒否した。旧Stage106公開APIは新型を拒否し、旧8–1/79eventの実行JSON同値とDB bytes不変を回帰確認した。

初戦／決勝のinsert途中・commit直前・初戦commit後・決勝計算直前・完了commit後応答前、exclusive lock、WAL/DELETE、同時append、RO書込拒否を確認。決勝commit直前の子をdirty-page spill後に強制終了し、RO readerがhot journalを復旧せず拒否・原本/sidecar bytes不変となることを確認した。自己所有fixtureだけ明示的SQLite recovery後、初戦が残り決勝と順位がない状態へ戻り、同じstoreで再試行成功。単一SQLiteの各試合transactionの原子性であり、大会全体やJSON／複数製品DBを同時に原子的保存したものではない。

## 測定・受入

Linux Python3.12.14補助測定（全unittest・関東E2Eとの並行実行）。新headless/旧9版gateは22 tests、skip0、93.952秒、成功。初戦commit後348,160 bytes、決勝後475,136 bytes。子1の開始・計算・検証・保存・終了1.147497秒、再開子2の同処理1.948355秒、完了readerの全検証0.245531秒。RO読取前後のDB bytes不変。性能はWindowsや長期scaleを保証しない。

新Windows Python3.12専用CIはheadless22件とnative mapped Tk1件をskip0必須にする。Tkは2つの実worker終了後に2回新windowを開き、3team・4校・各試合・全イニング・永久IDの試合別／累計、未完了／破損／navigation読取失敗時の全消去、native close/rename/reopenを検証する。ローカルLinux環境は表示サーバー未導入のため新TkはWindows CIで受入する。最終headのWindows CI・全unittest・関東17校E2E・Stage94–106既存ゲートの結果はPR本文に記録する。個人Windows PCの人による目視・手操作は未検証。

初回Windows Tkでは表示・ナビゲーション・拒否検証後の共通integrity sweepが、意図的に作った破損fixtureまで検査して失敗した。破損拒否の検証後にそのfixtureを片付け、有効なSQLiteのclose/rename/reopen検証を継続するようテストを修正した。製品／lab readerの破損拒否は維持した。

修正後Windows Python3.12.10のnative mapped Tkは1 test、skip0、21.023秒で成功。添付集計JSONでsuccessful/native_windows/mapped_tk、DB475,136 bytesとRO bytes不変を確認した。Linux全unittestは2,325 tests、1506.737秒、成功（表示環境等によるskip52、既存skip条件は変更なし）。別実行の関東8都県17校E2Eは2 tests、skip0、295.529秒で成功。PR #268の全16workflow一覧とも突合し、Stage91–96の6workflowのpath filterすべてに新labを追加した。新Stage107を加えた17workflowを最終headで再確認する。

Stage94/99/100/101/102/103/104/105/106の9候補は真の各main checkoutから独立プロセスで自己生成exportし、現行readerでread-only内容verify・原本bytes不変を確認。Stage106は変更前にも実候補を確保して再verifyした。338catalog入力・106CSVを含むdata全bytes不変。内容verifyは真正性署名でも新しいreplay/restore承認でもなく、古いcatalogのreplay拒否を維持する。実ユーザー候補・既存save利用0件、実ユーザーsave互換は未検証。

## 限界と停止条件

既存Stage106までのAPIと新Stage107契約は別入口。全国正式GUI・製品大会/writer/save接続、全国合同一般化・山梨公式32team31試合、2027年開始、既存slot移行・上書き・本番restore/import/activation、履歴削除/GC、配布EXE化は行っていない。年数上限を導入していないが、今回の実証は2026固定2試合のみ。所有TemporaryDirectoryのcleanup後の永久保管を製品長期保存とは呼ばない。ADR-037/038/039/040はProposed・製品未採用。

PRは全最終head必須CI成功後も未マージ・auto-merge無効のレビュー待ちで停止する。
