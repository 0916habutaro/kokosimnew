# Stage43G-114 保存2027ロスターの架空練習試合・年度横断履歴設計

## 前提と対象

Issue #283。ユーザー承認によりPR #282がmainへマージされたことをGitHub APIで確認した。
マージcommit `2804a1ab7552d36f58bb839e8f448815f8b77747` と一致する作成済み
`stage43g114-2027-practice-match-history` を使用する。
実在学校master、架空選手・架空試合、Windows専用・個人利用・非配布の試験である。
EXE/installer、新全国GUI、既存saveのmigration/restore/削除/GCは対象外。

## 既存依存の棚卸し

|既存コード|年・seed・登録・出典依存|今回の扱い|
|---|---|---|
|`game_core/players.py`|永久ID、school/program、入学年、学年、氏名、守備・利き手・slot。初期20人の学年5/7/8|2027初期再生成禁止。保存Playerを使用|
|`game_core/career_rosters.py`|隣接年度、同career_seed・学校を要求。進級は学年だけ+1、新入IDは年度/学校/slotの専用recipe|既存継承を保持。2027は8/5/7、396進級・264新入・264卒業|
|`career_roster_archive.py`|年/学校PK、academic_yearのみ除外した恒久identity、保存前年度からの原子的追記|schema/writer変更なし。保存2027 JSONを直接decode|
|`yamanashi_annual_rosters.SelfCreated2026.verified`|自己所有capability、2026年33校660人・640登録・31保存試合・32順位、schema/封印/seed/event/bracket oracle/bytes|全件検証を必須とし未完了を拒否|
|同 `AnnualRosterLab`|別隔離DB、校別追記、33校のannual_acceptance、924累計IDのlineage|型・出典・全受理を確認してから直接SQLを読む|
|同 `browse`|監査後の期待transitionから閲覧用rosterを構成|試合入力に使用しない。`saved_authority` が実保存JSONをRO decodeし全件照合|
|Stage112 `school_roster_contract` / `VerifiedSavedSchoolSource`|共通受付は学校年度の整合性のみ。Stage111 adapterだけが全31保存検証を行う|source_kind文字列だけでは認可しない|
|Stage113 `SavedSchoolRosterSource/Trial`|100校の2026 roster-only保存→2027継承。大会開始gateは常にfalse|2026大会完了出典として拒否。正出典に代用しない|
|`joint_team_registration_lab`|2026固定fixture、登録集合、`_team_input`のYEAR/ROSTER_SEED|旧validator/登録/能力入口を緩めず、新入力を独立構築|
|`yamanashi_tournament_registration`|YEAR=2026、CMP000041、roster/ability seed430103、selection430108、32team/33school|2026原本検証専用。2027公式entryや合同継続を生成しない|
|`yamanashi_tournament_lab`|2026固定日程、bracket seed、match_id、winner連鎖、前結果checkpoint|2027には不使用。yearだけ変更した入力を作らない|
|`registered_match_driver._run`|入力scope/能力/打順/投手、PA乱数 `lab105:{match_id}:pa:{number}`|新しい出典validatorを通して実計算部を再利用|
|`registered_full_a_contract`|版 `registered_team_full_a_v1`、モデル `lab105_partial_probability_fixed_advancement_v1`、全行の年・scope|内側の完全A結果型を保持。外側の入力・DB・履歴に練習試合種別を明示|
|`registered_full_a_oracle.event_oracle`|乱数やdriverの走塁/成績関数を呼ばずイベントから全得点・イニング・投打・責任投手を再集計|独立検証として再利用。固定登録に依存する旧公開validatorは不使用|
|`yamanashi_tournament_store` / reader|登録・計画・進出台帳・順位・全31結果を一体監査|2026履歴のRO出典のみ。2027を旧DBへ追記しない|
|`yamanashi_demo_store`|namespace、実体ID、lease、Windows pin、リンク/reparse/sidecar/hot journal拒否|安全helperを再利用。既存marker/schema/writerは変更しない|

## 出典・選出・版付き入力

`saved_authority` はexact typeのStage111 `AnnualRosterLab`だけを受け付ける。
`source.verified`→年次全行/profile/lineage/受理監査→年次DBの2027保存JSONをRO SQLで直接読む。
全33校の学校集合、各20人、年、canonical bytes、digest、期待継承値を照合し、前後DB SHAとsource bytesを確認する。
元sourceと年次sourceのroot/file/lease実体ID、契約、2026 checkpoint、2027保存digest/受付/DB SHAをreceiptに固定する。
同bytesの別年次DB、未受理、roster-only、任意saveパスは代用できない。

保存登録で単独teamの学校だけを抽出し、保存学校ID順の先頭2校を実masterのprogram/名称と照合する。
合同構成校は除外する。各校全20人を入力に保持し、能力は保存Playerからreference_year=2027、ability_seed=430103で計算する。
先発Pはcontrol優先。残る8守備位置から、2026に実打席のある進級者と2027新入生の両方を含む合法な9人を
contact合計最大・IDで決定する。打順はcontact降順/ID、投手順はcontrol降順/ID。
条件を満たせなければ停止し、選手プロフィールを改変しない。

入力版 `stage43g114_practice_input_v1`、保存版 `stage43g114_saved_practice_v1`。
year=2027、record_kind=`fictional_practice`、match_id=`LAB114:2027:PRACTICE:match1`、match_seed=430114。
共通計算型に必要なcompetition_idは内部scope `LAB114:PRACTICE` とし、masterの実大会CMPを使わない。
source receipt SHA、保存roster SHA、選手能力、打順/守備/投手、usage recipeをcanonical入力に含める。
同入力/seedはcanonical結果がbit同値。実体IDを含む入力なので独立fixtureやOSを跨ぐdigest同値は要求しない。
未知校/選手、異年/seed/recipe/source、bool-as-int、旧source偽装、旧イベントのID置換は厳密再構成比較で拒否する。

## Stage105および製品MatchSimulatorとの関係

Stage105 `_run` をそのまま使用するため、**Stage105のイベント確率・走塁・成績計算との差異はない**。
異なるのは保存2027の出典、学校/選手集合、reference_year、練習試合scope、編成recipe、試合seed、保存先と履歴表示。
PA乱数namespaceも既存lab105を保持するがmatch_idが別なので旧2026イベントは転用されない。
私有計算APIへの依存はこの試験モジュール内に限定し、旧公開入口の固定2026契約は変更しない。

製品 `MatchSimulator` 全体とは次の差がある。

|項目|本試験で採用するStage105モデル|
|---|---|
|再利用|`_event_weights` / `_weighted_choice` / `_should_change_pitcher` とconfig。製品試合全体の再現ではない|
|走塁|安打の塁打数分の固定進塁。製品の単打/二塁打の確率的追加進塁は使わない|
|失策・野選|確率をfield_outへ合算、当該イベントは発生せず失策欄0|
|犠打・犠飛|状況別判定を使用せず成績欄0|
|盗塁・盗塁死|本driverでは発生せず成績欄0。製品側実装の有無の説明とは区別|
|投手責任|塁上走者の責任投手を追跡。失策なしモデルの失点は自責点に集計|
|交代・終了|投手交代で同打順置換。9回以降の裏省略/サヨナラ、30回/10000イベント上限。不成立は保存しない|

完全Aはこの明示モデルの得点・全イニング・投打全個人成績の完全整合を意味する。
oracleで走者/打順/交代/責任投手/得点/全成績を独立再構成し、別途同seedの全結果再実行比較を行う。
各校で進級者・新入生の実打席を確認する。異seedの結果を固定入力の結果として持ち込む操作を拒否する。

## 隔離保存と再開

source2026、annual2027、practice2027は別の自己所有TemporaryDirectory。親が所有者を保持する。
新targetは `practice.sqlite3` / `practice.lease`、版付き契約、結果、学校索引、選手索引のSTRICT schema。
全表UPDATE/DELETE拒否、全schemaと全行を監査。入力・結果・索引を同一transactionでappendする。
同一結果の再appendはbytes不変の冪等、異内容は拒否、競合はlease/BEGIN IMMEDIATEで拒否する。
DELETE journal、synchronous FULL、明示close、接続前のroot/file/lease identity、hardlink/symlink/junction/reparse、
未知sidecar/hot journal/header拒否を維持する。hot journalは自動回復しない。
複数storeを跨ぐtransactionは非原子的。書込後にもsourceを再監査し、変化時は公開拒否。復旧機構ではない。

保存後に全native handleをcloseしprocess終了、別workerが私有capabilityで再開する。
全出典・保存入力/結果・索引をRO再監査、独立oracle・seed再実行照合を行う。
commit直前/直後の例外・強制終了、hot journal、競合、実体差替、schema/索引/結果改ざんを検証する。
Windows close→rename→戻す→reopenも確認しGCに依存しない。

## 年度横断閲覧と禁止事項

`PracticeView.school` / `player` は要求ごとに検証したdetached view。
2026 `fictional_tournament` と2027 `fictional_practice` を明示し、学校には保存rosterと試合・全成績を返す。
永久player_idには元学校・入学年・transition、年度別profile/state、実登場時の投打成績を返す。
未登場と未知IDを区別し、新入生は2026未入学、卒業者は2027卒業・登場なし。
2026の合同戦績は保存大会teamの記録として保持し、単独校へ勝敗を付け替えない。
2027公式outcomes/schedule/qualificationはNone、season_start_authorizedはfalse。
公式順位・優勝・進出・日程・合同継続を作らず、旧writer/slot/`HistoricalMatchArchive`に書かない。
イベント保存は本試験の照合証拠であり、製品の全打席永続ログを必須にする決定ではない。

## CIと負荷

最小独立fixtureは保存31試合を一度作成し、2027全33校受理を一度行う。非破壊試験間だけ同一不変sourceを共有し、
各試験の前後SHAと全操作の監査を維持する。practice targetは試験ごとに分離し、故障sourceは復元後SHAを確認する。
既存Windows年度jobへ専用auditを追加し、新OS行列/jobを増やさない。新専用fixtureはskip0を要求する。
Stage100–113のnative Tk/SQLite、全unittest、関東8都県17校E2Eを保持。
旧Stage94/99/100/101/102/103/104/105/106/107/108/109/110/111/112/113の16版を、既存15版gateと
変更前Stage113マージcommitからの自己生成exportでRO内容verifyする。restore/replayせず、catalog338と106CSV bytes、元候補bytesを比較。
新モジュールはcatalog338入力を編集せず、既存製品save/backup/履歴やStage113 sourceを入力・更新しない。

実測は別報告書とaudit JSONにOS/Python/SQLite、件数/skip/失敗、時間、DB bytes、試合内訳、CI URLを記録する。
Windows hosted CIと個人PCの目視・サインアウト/ログイン・OS再起動は区別し、後者は未検証ならそう明記する。
最終headの全必須CI成功後も未マージ・auto-merge無効・レビュー待ちで停止する。
