# Stage43G-99 SQLite接続寿命・旧バックアップ互換調査報告

PR #252マージ済みmain `37f3937`から専用ブランチ`stage43g99-sqlite-lifetime-legacy-compat`を作成した。Windows専用・個人利用・非配布のゲームとして、接続の明示解放と旧方式A候補の保全を扱った。[設計書](stage43g99_sqlite_lifetime_design_20261014.md)に実呼出し所有境界・版ごとの判定・段階導入／ロールバックを記録した。

## 変更前と変更後

|対象|変更前|今回の結果|
|---|---|---|
|ロスター保存／年度進行／read|with-only接続がGC依存|`CareerRosterArchive`にfinally close所有context、roster／年度一覧にclosing。既存transactionの順序・SQL・返却値を維持|
|大会結果保存／read|archiveの生`_connect`を直接利用|`CareerCompetitionOutcomes`が既存archive `_connection`でcloseを保証|
|履歴4短期read／学校・選手generator|with-only接続や消費側例外後のgenerator残留|`CareerHistoryBrowseModel`、`CareerLongitudinalReadModel`、`CareerPlayerRecordView`にclosing。反復元と消費側の寿命を明示|
|旧候補verify|固定1版だけを受け付ける。現行replay可否を示さない|旧aggregate digestを保持し現行版を追加。両版の内容を版固有digestで検証。旧候補へのwriteなし|
|現行環境との比較|明示した独立診断なし|`diagnose_candidate_compatibility`／`compatibility` CLIを追加。旧候補内容は健全・現行replayは拒否を別値で返す。現行338一致でもreplayの自動承認なし|

製品寿命変更は上記5ファイル。`HistoricalMatchArchive`、`LiveGameService`、`SaveSlotManager`、slot session／bridge、Stage98デモ補助は変更していない。338集合は不変、5ファイル以外333件は変更前と一致。data内106 CSVを含むdata全ファイルの集合／bytes不変を確認した。個別SHA/path一覧は公開しない。

## 旧候補の検証

寿命修正前のmainを私的checkoutへ展開し、別Pythonプロセスで自己生成停止済み模擬旧Aのexport／verify成功を確認して候補を保持した。変更後に同じ候補のreceipt・manifest・全原本／SQL／338 digestをverifyできた。生成元の版は旧版、導入済みの版はStage99で、変更した5ファイルの差異を確認した。

旧候補内容の健全性は受理するが、`installed_catalog_match=false`／`catalog_mismatch_refused`／`current_code_replay_allowed=false`。候補内Pythonを実行せず、`load_game`呼出しもテストで禁止した。未知版、版名のみの差替え、receipt・JSON・互換ファイルの改ざん、欠損、検証途中変更は拒否する。未知の導入済みコードでも健全な旧候補を破棄しない。unsigned evidenceから生成時版の真正性は証明しない。

## 検証結果とCI受入

|検証|確認結果／受入条件|
|---|---|
|Linux補助Python3.12・専用製品／互換回帰|13件成功・skip 0。変更前の実export候補→変更後verify／診断、現在候補のexport、改ざん／競合拒否|
|同一プロセス製品寿命|new→6試合→manual/autosave save・load→7試合→seal、実ロスター／大会結果保存・冪等read。保持した接続のcloseとrename／再読取、実runtimeの完全AとSQL原本7試合一致|
|例外／rollback|ロスター競合・新年度identity／roster挿入途中例外・schema例外・transaction終了例外・未知年・破損履歴・集計消費側例外。例外frameを保持しながらclose確認。元bytes不変／部分保存なし|
|Linux補助mapped Tk|1件成功・skip 0。製品のcloseを検証前に代行する補助なし。実ボタンで年度→学校→試合→選手、戻る、外部slot拒否、read例外、子窓二重終了、root終了／再構築、各操作後rename|
|Windows主要CI|専用2ジョブで上記13件＋native mapped Tk 1件をzero skipsで必須実行。with-onlyの使用中DB rename拒否をWindowsで再現。解放後rename／再読取を検証|
|Stage94–98|既存workflow／検証件数を維持。Stage94新規exportと候補verify、Stage95–96隔離実験、Stage97実プロセス再起動、Stage98保存／GUI終了／manual・autosave再開|
|全Python unittest／関東17校E2E|既存Python3.12全suiteと関東8都県17校の専用2件を維持。旧main fixtureのGit履歴を使うため全suite checkoutにfetch-depth 0を追加。最終headの全CI成功を受入条件とし、実行数・workflow URLはPR検証欄へ記録する|
|既存セーブ|作業環境の候補0件、未検証・入力利用0。件数確認だけで実保存を開かない|

Stage98のwriter子プロセス終了や`demo_read_handles`の一括closeによる成功を、製品寿命修正の証明に使っていない。Stage99は接続参照を保持して製品が先にcloseしたことをassertし、その参照を保持したままDBをrenameする。公開artifactは集計JSONだけで、候補・旧checkout・evidenceを添付しない。

## 未対応と停止条件

全製品SQLite APIの普遍的close保証、cache writer／BrowseRepositoryの残る経路、本番facadeへのロスター／大会結果統合は残課題。[ADR-035 Proposed](../adr/ADR-035-sqlite-lifetime-and-backup-replay.md)に分割案を示した。旧バックアップの現行replay互換・生成時真正性・製品restoreは未証明／未導入。Windows CIは自動操作であり、人の個人PC実操作・目視は未検証。

既存セーブの移行・上書き・履歴削除、本番restore、保存スキーマ変更、年度上限、方式B/C、正式全国GUIの大規模実装、配布対応は行っていない。全CI成功後もPRをマージせず、auto-mergeなしでレビュー待ちとする。
