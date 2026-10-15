# Stage43G-109 Windows山梨夏 永続デモ実装報告

## 到達範囲

最新main `75da94e91445898b4f090ba31155958562230407` から専用ブランチで開始。Windows Python 3.12/Tk用の独立画面とGUI非依存controller、専用永続namespace/storeを新規追加した。起動は `py -3.12 -m phase2_engine.yamanashi_demo_tk`。新規専用保存先の明示作成→別IDの32チーム新規デモ→次の1試合/ラウンド残り→試合ごとの自動保存→終了→Python完全終了→専用デモIDの明示再開→大会/学校参加/個人成績閲覧を提供する。

Stage108登録・plan・試合モデルを再利用し、旧TemporaryDirectory writer、固定fixture、reader、338互換catalog、106CSV、製品save/writer/schemaを変更していない。既存Stage91～96のpathsにStage109を追加し、必須の旧Windows/実Tk回帰が今回も動くようにした。テストの削除・間引きはない。

33校660永久ID、32team640登録、合同10＋10と未登録20人、5ラウンド31試合、スコア・全inning・実出場投打成績を保持する。同1/2/3/5/9/17位を表示し、合同勝敗・優勝を元学校の単独勝敗へ複製しない。全660人の試合別と通算、未出場/未登録者も選択できる。学校公式表示名対応と架空結果の区別は画面の常時表示とヘルプに示した。

## 保存境界・中断

未存在の新規ルートとUUID子ディレクトリをexclusive createする。任意SQLiteを受け取るwriterはない。新規専用版marker、namespace/demo/DB実体identity、recipe、schema/登録/plan/確率設定SHAとDB正本metadataを検証する。全保存済み試合をROで独立event再集計・同seed再実行・bracket oracle・SQL/SHA比較してからwriterを許可する。

OS排他leaseはプロセス終了で解放され、Windowsでは実体の置換を抑止するhandleも保持する。symlink/junction/reparse・hardlink・コピー/実体差替・未知版・未知ファイル・旧製品/backup領域は拒否する。journal/WAL・SQLiteロック・破損は原本を書き換えて回復しない。RO検査で原本bytes不変を照合する。SHAは整合性で、第三者真正性署名ではない。

画面処理と計算workerを分離し、Tk widgetはメインスレッドだけが更新する。終了要求は未commit計算の取消を通知し、commit前ならrollback、commit後ならその試合だけが残る。終了はworkerとnative接続の完了を待つ。markerを毎試合更新せず、別JSON checkpointは置かない。原子性は単一SQLiteの1試合transactionだけ。

## 検証状況と証跡

Stage109専用auditはheadless 16 tests（新規→独立Pythonプロセス1→16→31、故障試験、旧11版）、native mapped Tk 2 tests（新規・保存・アプリ終了・別Python再起動・続き・全32team/全660人選択・scroll・中断取消・破損時消去・close/rename/reopen）をskip 0で要求する。Windows Python 3.12専用workflowを追加した。全unittestと関東8都県17校E2E、Stage91～108の必須CIも維持する。最終headの結果と実測はPR本文およびCI集計artifactに記録する。

真のStage94/99/100/101/102/103/104/105/106/107/108 main checkoutから独立生成した11版候補をreadonly内容verifyする。実ユーザー候補は0件で、実ユーザーsave互換性は未検証。個別原本SHA・秘密の絶対パス・実ユーザーsaveをartifactへ記録しない。

初期のLinux補助試験で、RO SQL接続に対するDELETEでappend-only triggerを試すテスト前提の誤り、非表示タブへのscroll判定、破棄済みTk参照がworker GCへ残る問題を検出した。trigger拒否の専用RW接続、表示タブ選択、Tk所有スレッドでの終了時参照解放へ修正した。RO診断の制約は緩めていない。

## 残課題・高速化案

Windows runnerでの実Tk自動操作と、本人の個人PCでのマウス操作を区別する。個人Windowsの手操作・ログインセッション/OS再起動跨ぎは未実施で、日本語手順を別添した。固定位置の同一実体を再開する狭い試験で、移動/コピーimportやjournal回復手段は提供しない。実体IDを検証できないファイルシステムは拒否する。

旧候補生成はStage別に重複している。次Stageでは、同一OS/Python/旧commit/338catalog入力をキーに、一回生成した**読取専用fixture artifact**を各gateの別コピーへ展開する案を検討する。各コピーの独立bytes照合、故障試験の独立所有、候補コード非実行、真の旧checkout生成を残し、生成過程のgateも保持する必要がある。今回の必須検証を削除していない。全prefix再検証の省略や未検証DB cacheによる高速化も行っていない。

本番restore/import/activation、既存saveの移行/上書き/削除、2027実開始、全国進行/正式GUI、GC、EXE/installerは未対象。ADR-042はProposed（製品未採用）。最終headの全必須CI成功後も未マージ・auto-merge無効でレビュー待ちにする。
