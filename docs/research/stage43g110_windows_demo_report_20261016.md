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

## 検証・最終CI証跡

追加controller試験2件はLinux補助で21.190秒、mapped Tk追加2件は28.666秒、いずれも成功・skip0。中断時の再検証拒否、commit直後の中断、各1〜4件の進捗ACK、Tkメインスレッドの反映、多重操作拒否、応答継続、独立reader＋raw SQL/完全A、未登録とタブ切替時の破損拒否を確認した。

既存Stage109 headless16件/実Tk2件と、追加Stage110 headless3件/実Tk2件を同じWindows workflowの2 jobsで実行する。旧11版gateをそのまま保ち、真のStage109 main自己生成候補を追加して12版とする。Windowsのpaired計測には旧Stage109作成・完全終了後の新コードでのRO再開と30試合追記も含める。最終headの全unittest、関東17校E2E、既存Stage91〜109 CI、Windows native mapped Tk、旧12版の結果・秒数はPR本文とCI集計artifactに記録する。未実行の検査を成功とは記載しない。

## CI時間の観測と別案

Stage109最終headの[Python tests run](https://github.com/0916habutaro/kokosimnew/actions/runs/38752426352)の実stepは、全unittest **3,146秒（52分26秒）**、関東17校E2E **500秒**。job全体は3,154秒/506秒で、主因をcheckoutやsetupの待ち時間とは扱わない。旧候補の真正なcheckout生成・内容verifyが複数Stageとfull suiteで繰り返され、Stage108/109の全prefix再検証・故障・独立プロセス試験も積み上がっている。ただし個別テスト別の52分全体の寄与率は未分解で、原因別秒数を捏造しない。

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
