# Stage43G-97 Windows個人用ゲームの操作導線・縦断受入設計

対象はWindows専用・個人利用・配布しない高校野球ゲーム。起点はPR #248マージ後のmain `43f9754b2aa6c1018c4ad4e78faf1a6a98aa0d82`、Issue #249。Linuxは共通ロジックの回帰補助。Python 3.12から起動する開発形態を維持する。

## コード上の接続調査

|入口・接続先|現状実行できること|未接続・制限|
|---|---|---|
|`examples/run_browse_gui.bat` → `phase2_engine.browse_gui`|既存browse DBと学校・大会データの閲覧|LiveGameServiceの新規/保存/ロードへの統合入口ではない|
|`phase2_engine.live_game_cli` → `LiveGameService`|new/list/status/save/recoveries、当日試合/日付進行、manual/autosave|既定resolverの経路と能力試合は区別する。CLI起動だけで能力モデルのOption A完成ゲームとはいえない|
|`LiveGameService.new_game/load_game` → planner/runtime/SaveSlotManager|再現可能なJSON保存、試合を再計算するロード、archive同期|通常のロードも同期書込み経路。閲覧専用と混同しない。8校固定plannerは今回の試験用制限|
|`play_today/next_day/advance_through`|試合日のautosave、JSON保存後に歴史archive同期|本試験は能力resolverを明示注入した8校単大会だけ。全国career完成の証明ではない|
|`SaveSlotManager`|manual/autosave、rolling backup、復旧候補、タイトル|Stage94の独立exportとrolling backupは別。既存のrecoverは同じスロット内チェックポイント昇格で、本番独立backup import/restoreではない|
|`LiveGameService.finalize_season` → HistoricalMatchArchive|年末の試合数検査・年度封印|翌年の大会グラフ・試合開始を実装しない|
|`CareerRosterArchive` / `CareerCompetitionOutcomes`|保存ロスター・選手ID、封印済大会結果の保存と検証|サービスの毎回の試合保存から自動接続されていない。本試験が明示的に接続|
|`HistoricalMatchArchive.register_next_year`|翌年の台帳登録|登録は翌年の試合進行の証拠ではない。本試験2027年は試合0件、封印試合数は未確定NULL|
|`CareerHistorySlotSession` → bridge/catalog/read model|保存スロット → 封印年度 → 保存学校 → 試合/選手、学校戦績|進行中年度は封印年度候補として表示しない。ゲーム再開メニューからの統合遷移はない|
|`CareerHistoryTkPilot`|日本語保存校名、スコア、各イニング、打撃/投手成績、選手の年度集計、戻る/再読込|独立した閲覧専用試験GUI。正式ゲームGUIではない|
|`career_cross_era_gui_pilot` / `career_tokai_season_gui_pilot`|既存の履歴・年度操作等の限定pilot|固有の研究fixtureやcontrollerの導線。全ゲームの統合導線ではない|
|`hiroshima_stage13e3g35_preview_gui`|FMT025の表示/次結果/リセット等の操作試験|隔離preview、セーブを進める正式ゲーム操作ではない|
|Stage94 export/verify、Stage95/96試験|停止済み単大会の独立backup、自己生成候補だけの隔離copy・再生|本番restore/import/activationは導入しない|

## 最小受入シナリオ

1. 新しい一時領域を作成し、実サービスで2026年8校単大会を新規生成。固定seed・能力resolverを明示注入する。日本語の保存パスとタイトルを使う。
2. 6試合まで進行、試合日のautosaveを経てmanual保存。期待値は保存JSON/DBを読む前のruntime試合出力から取得する。
3. Pythonプロセスを終了し、別作業directoryの別プロセスでmanualまたはautosaveを明示選択して実ロード。同期済み原本の全ファイルSHAが変わらないことを検査する。
4. 残り1試合を進め、年末封印。テストがロスターと大会結果を明示保存し、autosaveを確定する。この接続を製品完成として扱わない。
5. 閲覧モデルへ移り、8校すべての試合リンクから全7試合のスコア・イニング別得点・チーム/打撃/投手成績を確認。保存校名の年度出典、所属school ID・player IDを確認。学校勝敗と各校の打者/投手の代表選手の集計値をruntime出力から独立集計する。
6. 再終了・実ロードの全7試合一致、翌年2027の台帳だけの登録、2026封印記録の参照を検証。翌年試合進行は拒否される。2027の試合0件と、候補一覧に2026しか出ないことを検証する。
7. 実Tkで表示したwindowにイベントを送り、年度→学校→試合→保存レコード詳細→戻る→選手→戻る→不正slot選択の拒否→再読込を操作する。root終了・新しいrootで再起動を2回行う。試合を進めるGUIは追加しない。

全ファイルの読取前後SHA、SQLite `integrity_check`、行ごとのSHAを独立に検査する。スコアと各halfの得点総和、team ID、個人成績を検査。破損SHAの拒否時はナビゲーション状態と原本不変、自己生成fixtureの捕捉済みbytesだけに戻して再試行できることを確認する。データ改変は試験一時領域のみ。

## Windows固有の受入

- 新規/ロードの子プロセスは絶対data/config/saveパスと異なるcwd、日本語パスを使う。製品CLIの相対既定値があらゆるcwdで使えると主張しない。
- SQLite接続はネイティブのまま使い、fixture内で既存Stage94の`owned_sqlite_handles`を適用して、例外後も明示解放する。生きた参照を保持したままfixture scope終了後`SELECT`が「closed database」となることを確認。これは**fixtureのhandle管理の検証であり製品側のhandle寿命修正の証明ではない**。製品側の一部旧読取/ロスター/大会結果APIはGCに依存する。
- 製品ソース338ファイルはStage94互換性カタログで固定されているため変更しない。製品のhandle寿命修正は旧候補verifyを維持する互換性設計と合わせて次Stageで判断する。schema/保存内容/過年度台帳を変更しない。
- 全handle解放後に日本語保存directoryをrenameして再読取する。**使用中ファイルのrenameやbackupが常に成功する保証ではない**。停止前の独立backupの拒否はStage94–96の既存回帰で維持する。
- GUIはWindows runnerの本物のTk・表示window・イベントループを使う。XvfbはLinux補助のみ。人がWindows実機で操作した検証とは区別する。

## CI優先度と限定調整

|優先度|実装・提案|合格基準|
|---|---|---|
|主要・毎PR|新workflow `windows-game-acceptance.yml` のWindows job|Python3.12、headless 3件/Tk 1件、skip 0、manual/autosave両経路、fixture専用、厳格Windows指定|
|補助・毎PR|同workflowのLinux job|同じoracle、Xvfb実Tk、skip 0、fail無視なし|
|既存・毎PR|`python-tests.yml` 全unittestと独立関東17校E2E|既存の分割を保持。全suite中の既存関東skipは独立jobの実行と組み合わせる。新規skip追加なし|
|既存・影響時|Stage91–96 backup/競合等のworkflow|既存チェック削除/弱体化なし|
|提案・次工程|Windows全suiteを週次またはworkflow_dispatchで実行|毎PR二重全suiteを避ける。旧fixtureのWindows handle解放・Linux固有契約を棚卸ししてから設定。今回未実装|

mainのbranch protectionは取得時`protected=false`。今回の「必須」はPRでWindows新job、Linux補助、全unittest、関東17校、および起動した既存CIがすべて成功する受入条件を指す。管理者のbranch protection設定変更は行わない。PRのChecksは最新headで確認し、成功後も未マージで止める。

## 正式GUIに進む前の不足・優先度案

|優先度|次工程の候補|必要な接続/判断|
|---|---|---|
|1|起動→新規/続きから→日付/試合→保存の統合画面設計|LiveGameService、能力resolver/ロスター供給契約、SaveSlotManagerの明示source選択。実装前に画面範囲をレビュー|
|1|ロスター・大会結果・保存の一貫したライフサイクルとSQLite handle管理|現在テストが手動で結ぶ部分をサービスに統合する設計。GC依存handleを明示closeする前にStage94固定互換性closure/旧候補verifyの維持を設計。既存save互換・例外時整合を先に定義|
|2|ゲームから保存履歴への閲覧導線|スロットID→CareerHistorySlotSession。進行中年度表示と封印年度表示を分ける仕様。学校戦績集計の日本語画面接続|
|2|年度更新の操作導線|年度封印→翌年ロスター→複数大会グラフ構築・資格/feeder。台帳登録だけを翌年ゲーム開始と見なさない|
|3|ゲーム内容・日常利用の実機受入|Windows PCで新規・終了・再開・成績閲覧を人が確認。長期全career/全国100・200年実進行は別検証|
|保留|本番独立backup restore|未承認。Stage95/96/97 fixture toolingを昇格しない|

Option Aのスコア/各イニング/個人成績全件保持・年数無制限方針を維持する。EXE、インストーラ、配布用署名、自動更新、クラウド同期、save migration、履歴削除/GC、新manifest/lockは今回追加しない。

## Windowsでのローカル実行（開発・自己生成fixtureのみ）

PowerShellでリポジトリrootを開き、Tk付きPython3.12を使用する。外部Pythonパッケージは不要。

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force audit-results | Out-Null
& $python tests/stage43g97_audit.py --require-windows --json-output audit-results/windows-headless.json
& $python tests/stage43g97_audit.py --require-windows --gui --json-output audit-results/windows-tk.json
```

JSON出力は既存fileに上書きしないため再実行は別出力名を指定する。テストは一時fixtureを自己生成し、利用者saveを入力に受け取らない。既存の履歴試験GUI単体入口は`python -m phase2_engine.career_history_tk_pilot --saves-root <絶対保存root> --slot-id <slot ID> --school-id ""`。表示には封印済年度・保存ロスターが必要で、完全なゲーム起動手順ではない。
