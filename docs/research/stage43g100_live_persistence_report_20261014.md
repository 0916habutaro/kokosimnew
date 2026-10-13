# Stage43G-100 製品保存ライフサイクル統合報告

PR #254マージ後の最新main `4ee0f91`から`stage43g100-live-history-persistence`を作成した。Issue #255に従い、試験workerの後付けロスター／大会結果保存を、製品`LiveGameService`の明示的初年度契約へ移した。[設計書](stage43g100_live_persistence_design_20261014.md)に出典・保存順序・失敗時・保証／非保証を記録した。

## 実装結果

- 明示的`InitialCareerPersistence`を追加。2026年の既知8校MAIN7試合だけを対象とし、未指定モードの挙動は維持した。試合前に確定したresolver入力を使い、暫定cacheを後付けで正本と扱わない。
- 初回manualから8校160選手の初年度snapshotと永久identityを保存する。全Aの選手ID・所属、個人statとスコア、MAIN結果と台帳を照合し、年度封印後だけ既存outcome writerで大会順位を確定する。
- manual/autosave・load replay・封印済再ロード・2回再保存を同じ導線に接続。部分commitの安全な再試行と、source不一致／古いsave／破損履歴の拒否を検証した。複数正本間のatomicityは保証しない。
- worker自身による`resolver._roster_cache`採取と`save_initial_roster`／`record_completed`の後付け呼出しを削除。Tkに保存済大会順位の小さいread-only表示を追加し、学校／選手画面は既存経路を維持した。
- catalogは338入力集合を維持し、2製品依存変更をStage100固定版として識別。旧Stage94／Stage99 digestを保持し、旧2候補内容のverifyと現行replay拒否を両立した。

## 検証と受入条件

|検証|結果／条件|
|---|---|
|製品service headless正常・異常|11件。初回8校160選手、6試合両source replay、7試合seal、outcomes自動保存、再ロード2回保存。各DB snapshot不変とslot metadata更新を区別|
|失敗境界|JSON commit後、学校部分commit、match commit前、seal commit後、outcome commit後の応答前停止、学校／identity挿入rollback、source／ID／所属／学年／seed／A欠落／古いcheckpoint／封印台帳破損を試験|
|Windows寿命|製品接続を保持し、例外frameも保持したまま明示closeをassert。DB rename→復帰→integrity_checkを専用Windowsジョブで必須。Stage99のgenerator中断・GUI子窓終了回帰も維持|
|旧2版のpre→post回帰|3件。変更前の真のStage94／99 export候補を生成して保全。両版read-only verify受理、現行replay false、版名差替え拒否。導入済一致の現行候補でもreplay未承認|
|変更前workerと新製品サービス比較|独立raw SQL／SHA oracleで8 roster・160 identity・7試合の全A／player_id・1大会順位・年度台帳の一致を確認。旧codeはGitのreview済checkoutから試験だけで実行し、候補内Pythonは実行しない|
|native mapped Tk|両sourceで新規→6試合→保存→別プロセスload→7試合seal→学校戦績／個人成績／大会確定順位→read-only byte不変。Windows専用1件zero skips、Linux補助も同じ試験|
|既存Stage94–99|既存workflowを維持。Stage99の変更差分oracleは原来5件＋今回2依存を明示して更新|
|全Python unittest／関東17校|既存Python3.12全suiteと関東8都県17校専用2件を実行。最終head全CI成功をPRの受入条件にし、件数・workflow結果はPRに記録|
|master106CSV／data|集合・bytes不変。Stage99 catalogの残り336入力も不変。private個別SHA／path／候補本体を公開しない|
|既存save|作業環境0件・未検証・試験利用0件。内容を開かず件数だけ確認|

専用Windows CIは製品14件とmapped Tk1件をzero skipsでgateする。Linuxは補助検証。全suiteの環境別skipと専用ジョブのzero skipsを混同しない。公開JSONは環境・件数・成功／失敗・保証範囲だけで、候補／旧checkout／private SHAを添付しない。最終CIの成功を確認したうえでPRをレビュー待ちにし、マージ／auto-mergeは行わない。

## 制限と次Stage

全国career／任意他大会／翌年全進行の完成ではない。県別pre-MAIN、複数大会で共有する所属の正本、年次roster advance、資格／feederの保存責任を次の設計で扱う。新しい出典型はfail closedのscopeを緩める前に独立検証が必要である。[ADR-036（未採用）](../adr/ADR-036-career-persistence-expansion.md)に拡張の判断条件を残した。

既存save移行・上書き、schema migration、製品restore、履歴GC／削除、正式全国GUIの大規模実装、配布対応は実施していない。電源断による破壊、同時writer、他年度／他モードの修復、旧候補生成時真正性／現行replay互換、すべてのSQLite APIの寿命、人のWindows個人PC目視・操作は未保証／未検証である。
