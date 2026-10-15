# Stage110 WindowsデモUIと処理時間の実測報告

## 実装

Stage109マージ済み最新mainから専用ブランチで実装。初回/再開手順、demo ID欄、保存済み進捗バー、前試合・次戦・ラウンド残数、未登録/未出場と成績タブ導線を追加した。ラウンドの各commit後にTkメインスレッドが進捗を反映し、workerはwidgetを操作しない。多重クリックと保存先切替を禁止し、進行を中断する操作では要求・検証完了・未保存を区別する。

処理改善は2箇所：書込み直前の全件監査が照合した行を同じtransaction内で再利用し、INSERT差分検索をset化する。未表示の個人成績表はタブ表示時にguardして構築する。書込み前/後、別プロセス/再起動時の`_audit`、独立event/bracket oracle、seed全再実行、schema/SQL/SHA比較をすべて維持する。marker/schema/recipe、製品writer、338catalog、106CSVに変更はない。

## 初期のLinux補助実測

Python 3.12.14、同じホストで固定Stage109 mainと新版を順次実行。各31試合を1試合ずつ進行し、1/16/31件で別readerと再開・mapped Tkを確認した。inclusive時間は重複するので合算しない。初期プロファイルとの負荷重複があったため、この1組の差をそのまま個人PCの改善率とはしない。Windowsの同一job前後比較を最終証跡とする。

|項目（秒）|Stage109|Stage110|
|---|---:|---:|
|新規デモ作成・検証|4.280356|4.427375|
|1試合操作×31の合計（計算/全検証/保存/再読込）|215.971894|178.266128|
|transaction合計（前後監査・SQL・commit含む）|100.760002|77.589980|
|新規試合計算31件のみ|0.158464|0.130115|
|行生成の累計・呼出回数|108.936050 / 259|84.440080 / 228|
|1件での再開|2.173176|1.923566|
|16件での再開|2.730683|2.181522|
|31件での再開|3.019281|3.139135|
|1件でのTk show＋update|0.121687|0.162498|
|16件でのTk show＋update|0.015252|0.012593|
|31件でのTk show＋update|1.083929|1.089008|

全件監査164回・RO read/verify101回は両版同数。追加の独立readerは別プロセスでありこの累計外。行生成が31回減ったことが再利用の直接の証拠で、再開やTk時間は改善しない点/改悪した点も表に残した。新規試合計算自体は小さく、待ち時間の主因は全件検証・行生成である。検証を削って短縮していない。全32 prefixの同じDB入力で、実際の新版差分writerと旧list referenceのDB bytes一致を確認。差分処理のみは新版プロセス内でlist約0.113秒/新版約0.049秒であり、set化だけの体感効果は小さい。

1/16/31件のDB bytesは両版とも1,318,912 / 3,223,552 / 5,124,096。全31試合の完全A・入力・SQL各行・順位・学校履歴は同値。別namespace固有metadataはcross-namespace比較から除外し、同metadataでの32段階DB bytes同値試験を別に行う。独立reader前後のDB bytes不変も確認した。個人成績を遅延構築する効果は、非表示時の集計呼出し0回として追加Tk試験で確認する。Tk描画全体が一律に速くなったとは主張しない。

初期プロファイル終了後、同じPython/ホストで順次再測定した。31操作合計は **153.206585→141.646908秒（約7.5%減）**、transaction合計 **72.059344→61.836928秒（約14.2%減）**。監査164回と行生成259→228回は同じ。1/16/31件のTk show＋updateは旧0.087063/0.061191/0.413838秒、新0.160976/0.009788/0.432078秒で、一律の描画速度改善はない。新規作成は3.067740→3.058704秒、再開1/16/31件は旧1.680720/1.999633/2.447981秒、新1.565776/2.045901/2.409964秒。旧Stage109の別プロセスが1件保存して完全終了→新版がRO bytes不変を検証→残り30件を保存し、旧版31件とSQL/完全A同値の確認も成功した。初期組とこの組を混ぜて改善率を算出しない。

## 検証・最終CI証跡

追加controller試験2件はLinux補助で21.190秒、mapped Tk追加2件は28.666秒、いずれも成功・skip0。中断時の再検証拒否、commit直後の中断、各1〜4件の進捗ACK、Tkメインスレッドの反映、多重操作拒否、応答継続、独立reader＋raw SQL/完全A、未登録とタブ切替時の破損拒否を確認した。

先行Windows headlessでは既存16件・旧11版は成功したが、追加controller試験1件のTemporaryDirectory削除でleaseが開いているためWinError32になった。試験が`addCleanup`に登録したcontroller closeより先にwithブロックのTemporaryDirectoryを片付けていたためである。lease/native pinやWindowsの拒否を緩めず、contextの逆順解放でcontrollerを必ず先にcloseする試験へ修正した。エラーを黙殺したりcleanupをskipしたりしない。最終コミットでWindows headless/実Tkと全必須CIを再検証する。

先行実装head `2f63f31` のWindows mapped Tkは既存2件と追加UX2件がskip0で通過し、同じjobのpaired計測stepへ進んだ。関東17校E2Eも2件・495.430秒で成功。最終版はGUI全660人閲覧前後のDB bytes一致も明示照合し、公開可能なpaired集計JSONをartifactとCIログの両方に出す。**最終headのWindows前後実測表・全CI結果の確定報告は[PR #276本文](https://github.com/0916habutaro/kokosimnew/pull/276)と同PRに紐付くCI集計を参照**する。実装コードと最終の資料・試験修正を区別し、先行headの結果を最終headの成功と取り違えない。

既存Stage109 headless16件/実Tk2件と、追加Stage110 headless3件/実Tk2件を同じWindows workflowの2 jobsで実行する。旧11版gateをそのまま保ち、真のStage109 main自己生成候補を追加して12版とする。Windowsのpaired計測には旧Stage109作成・完全終了後の新コードでのRO再開と30試合追記も含める。最終headの全unittest、関東17校E2E、既存Stage91〜109 CI、Windows native mapped Tk、旧12版の結果・秒数はPR本文とCI集計artifactに記録する。未実行の検査を成功とは記載しない。

## CI時間の観測と別案

Stage109最終headの[Python tests run](https://github.com/0916habutaro/kokosimnew/actions/runs/38752426352)の実stepは、全unittest **3,146秒（52分26秒）**、関東17校E2E **500秒**。job全体は3,154秒/506秒で、主因をcheckoutやsetupの待ち時間とは扱わない。2,350テストの完了ログ行の時刻差をモジュールごとに集計すると、以下の概算になる。隣接テストの終了処理等を含む区間であり、関数のprofiler値ではない。

|既存unittestモジュール|概算秒|
|---|---:|
|Stage102 master scale|370.735|
|Stage109 demo|340.594|
|Stage96 continuation|318.970|
|Stage108 store|249.930|
|Stage53 東海4県→地域|227.868|
|Stage47 東北4県 feeder|217.165|
|Stage9 神奈川FMT006|152.834|

上位4モジュールだけで約1,280秒。互換性と名付けられたテストモジュール群は計約127.831秒だが、他のテスト内のfixture生成はこの分類に含まれない。したがって「旧版候補cacheだけで52分を解消できる」とは判断しない。全件検証・大会E2E・故障試験・独立プロセスの蓄積を維持した上で、改善案ごとの追加測定が必要。集計は`audits/phase2/stage43g110/ci_baseline_timing_20261016.json`に保存した。

将来案は同じOS/Python/旧commit/338catalog入力ごとの生成cache。真の旧checkoutからの生成gate、各利用先での全内容verify、RO bytes不変、replay未承認、fault試験の独立所有を残し、cache miss/hitの比較とレビューが必要。今回はcacheも必須CI改廃も行わない。既存19 workflow/43 jobsに新workflow/jobを増やさず、既存デモjobへ必要な検査だけ追加した。

## 本人PCの確認と保護事項

|区分|状態|
|---|---|
|Windows runnerの自動mapped Tk|最終CIで実行・結果はPR本文へ記録|
|本人の個人Windows PCの手操作|**手動未検証（実施結果未提供）**|
|Windowsサインアウト/再ログイン・PC再起動後の再開と実体ID保持|**未検証**|
|実ユーザーの既存デモ/save/backup|使用0件・変更0件。互換性を実データで検証したとは主張しない|

[個人Windows手動チェックシート](stage43g110_windows_manual_20261016.md)に実施順・症状だけの報告手順・拒否文言の文字例を記載した。秘密path・原本SHA・saveファイルを公開artifactへ載せない。journalの削除、実体IDの修復、既存セーブ変更、本番restore、履歴削除、2027開始、全国正式GUI、EXE/installerを行わない。原子性は単一SQLiteの1試合transactionのみ。OS強制終了/媒体障害からの完全復旧は保証しない。

全必須CI成功後もPRは未マージ・auto-merge無効でレビュー待ちとする。
