# Stage43G-116：保存2027からの架空3チーム大会・段階保存・永久ID履歴

2026-10-17、Issue #287。PR #286はユーザー承認によりmainへマージ済み。
起点は `8dd971c55fca0562f7137aeab293bd6db033064e`。
作成済み `stage43g116-2027-fictional-three-team-tournament` を使用する。
学校は実master、選手・結果はゲーム内架空。Windows専用・個人利用・非配布。

## 棚卸しと責務

|入力／既存実装|今回の利用範囲・境界|
|---|---|
|Stage110 `yamanashi_tournament_*` / Stage109 `DemoStore`|2026山梨32team・33校・31試合・完全A・封印・順位の保存正本。登録640と学校660を分離。2027へ転用しない|
|Stage111 `SelfCreated2026.verified`|全保存31試合のschema・行・seed・イベント・進出を監査。保存学校JSONもdecodeし、前後bytes照合|
|同 `AnnualRosterLab`|全33学校年受理・660現役・924永久IDの系譜。2026から396進級、264卒業、264新入。学校年受理は大会資格ではない|
|Stage112学校年共通契約／Stage113保存100校|roster-only出典には前年大会完了根拠がない。実行authorityとして拒否。既存writer・試験を維持|
|Stage114 `saved_authority`|所有capability・全受理・保存2027 SQL JSONを直接読む。閲覧用期待transitionや選手再生成を試合入力に使わない|
|同 `PracticeStore`|2027架空練習1試合（固定入力で0–3）。別DB・別種別。既存履歴をROで結合表示し、大会へ結果転記しない|
|Stage115 `dry_run`|entry・joint・qualification・district・seed・draw・scheduleの7契約と保存学校年／前年出典の独立digest。明示架空だけready、公式・製品開始は常にfalse|
|`registered_match_driver._run` / `event_oracle`|前者の計算のみ再利用。後者は乱数・driver進塁・成績helperを使わず全得点／イニング／投打／勝者を検証|
|既存Stage107 3team大会|2026固定入力・固定BYE・資格に依存するため実行入口を転用しない。増分appendと独立進出oracleの責務分離を参考にする|
|`CompetitionRun` / `CareerCompetitionOutcomes` / `HistoricalMatchArchive`|製品実行・封印結果の契約。Stage116の架空結果は追加しない。製品の年度開始authorityへ昇格させない|
|master `CMP000041` / 登録 `YEAR=2026` / 2026日程CSV|2026構造参照と既存正本監査だけ。年の置換で公式2027参加・資格・合同継続・日程を作らない|

新規は `saved_fictional_tournament.py` と `fictional_tournament_oracle.py`。
製品writer/schema/catalog、既存Stage111–115契約は編集しない。

## 実行要求と出典の再検証

`FictionalTournamentStore` は自己所有 `TemporaryDirectory`、正しいStage111
`AnnualRosterLab`、型付きStage115 `CompetitionRequest`、厳密boolの明示opt-inを要求する。
任意のsaveパス、slot、backup、caller作成GateReportを受け付けない。
要求本体から `dry_run` を再実行し、7個すべて成功と保存学校年／前年出典を検査する。
開始直前・append・再開・閲覧で同じ検査を繰り返す。ready報告の使い回しではない。
source receiptを再度直接SQLから取得し、gateの前年digestと一致確認する。

実行対象はStage115の明示3teamだけ：

|entry|元学校|登録枠|
|---|---|---|
|単独1|SCH000196（帝京第三）|20|
|単独2|SCH000197（北杜）|20|
|明示合同|SCH000202（山梨農林）＋SCH000220（塩山）|各10、合計20|

`fictional:` namespace、架空authority、`self-created declaration/`出典を要求する。
official/verified/URL/公式と紛らわしいsourceラベルは実行層で拒否する。
Stage115の読取dry-runがラベルの存在だけを許容する挙動は変更しない。
別年・別source・未受理・学校重複・他校／卒業選手・永久ID重複・20枠不整合・合同枠不均等・
2026登録や資格receiptのコピー・部分gate成功は実行不可。

版 `stage43g116_saved_fictional_tournament_v1` の契約には要求全体、全gate結果／digest、
出典receipt、独立scenario seed、組合せ／宣言日／試合seed、全登録能力／打順をcanonical固定する。
再開ではcapability内の要求本体を型付きdecodeし、出典から契約全体を再構築する。
capabilityやSHAは自己生成fixture内の整合性証拠であり、公式認証や署名ではない。

## 選手と計算

保存2027各Playerの永久ID・元学校・program・入学年・学年を維持し、能力だけを
保存Playerから2027／ability_seed430103で計算する。学校ロスターを再生成しない。
20登録枠のprimary Pをcontrol順で先発選定。各守備位置をprimary優先で割当し、
不足位置のみ登録野手から明示シナリオ配置する。保存primary_positionを書き換えない。
先発9人は重複なし・進級実出場者・新入生・合同各学校を含み、contact合計とIDで一意選出する。
投手交代は投手打順枠へ置換する。投手列の登録20枠／元学校も保持する。

独立scenario seedの既定は430116、draw RNGと各試合seedの導出を分離。
宣言seedがあれば当該teamにBYE、なければ独立seedで3teamをshuffleする。
4枠 `(BYE対象, None, 対戦1, 対戦2)`、bye1、実試合2。
準決勝相当を宣言日1、実勝者対BYE対象を宣言日2とする。
既定の2027-07-01／07-03は**架空シナリオ日**であり公式日程ではない。
試合scopeは `LAB116:2027:FICTIONAL:<namespace/seedのdigest>`、試合IDは末尾match1／match2。
2026大会・Stage114練習試合のイベント／スコアを使わず、新規乱数で実計算する。
入力には前結果checkpointを固定し、敗者進出・未保存の前試合・別日・別seedを拒否する。
所有root／file実体IDを出典receiptへ含めるため、独立fixture間やOS間の入力／結果SHA一致は要求しない。
同じ保存選手・scenario seed・namespaceからの組合せと実計算は再現でき、同一所有fixture内の再開では全結果SHAが一致する。

Stage105の計算モデルとの差はない。製品MatchSimulator全体とは次の差がある。

|項目|Stage116で再利用する限定モデル|
|---|---|
|確率・投手交代|製品の確率／重み選択／交代判定とconfigを再利用|
|走塁|安打の塁打数分の固定進塁。確率的追加進塁は使わない|
|失策・野選|発生確率をfield_outへ合算。失策欄0|
|犠打・犠飛・盗塁・盗塁死|本driverでは発生せず成績0。製品側の実装有無とは別|
|投手責任|走者の責任投手を追跡。失策なしモデルの失点＝自責点|
|終了|9回以降の裏省略・サヨナラ。30回／10000イベント上限で不成立は保存しない|

完全Aはこのモデルにおける得点・全イニング・投打全成績の整合である。
`event_oracle` はイベントから打順、塁、アウト、交代、責任投手、得点、全成績を独立再集計する。
別途同seedで結果全体を再計算照合する。新進出oracleは得点から勝敗を導出し、勝者申告だけを信用しない。
異seed結果、スコア／イニング／打撃／投手／元学校／勝者改ざんを拒否する。
既定seedで合同敗戦、別の独立seed430119で合同勝利を実計算し、双方とも構成学校の単独勝敗0を検査する。

## 増分SQLite・再開

元2026・年次2027・練習試合・今回大会は別TemporaryDirectory／別DB。
大会DBは `fictional_tournament.sqlite3`、独立lease。STRICT表は契約、試合、進出、順位、
最終受理、実出場選手索引。全表UPDATE／DELETE拒否triggerを持つ。

|段階|保存状態|
|---|---|
|作成|契約＋BYE進出。勝敗0、順位なし、優勝None|
|1試合commit|試合1＋完全A＋出場索引＋実勝者進出。順位なし、優勝None|
|2試合commit|試合2＋完全A＋出場索引＋進出＋team順位3＋checkpoint最終受理を同一transactionで追加|

`BEGIN IMMEDIATE`、DELETE journal、synchronous FULL。全旧行を照合して差分だけINSERTする。
既存試合の同一入力・結果再送はbytes不変のfalse、異結果は拒否。保存後ACK消失にも同じ試合IDで対応。
保存直前例外はrollback。1試合保存直後 `os._exit(73)` → 別processで全出典再検証 →
未完了閲覧 → 試合2実計算／commit → 別process RO確認を行う。
precommit強制終了でできたhot journalは自動回復せず、接続前に拒否する。

root／DB／leaseのfile identity、単一hardlink、symlink／junction／reparse、未知sidecar／WAL／SHM、
header、lease排他、SQLite lock、全schema／行／索引を監査する。
Windows native handle pinと明示close→rename→戻す→reopen、RO前後SHA不変を確認する。
複数SQLite間の一括atomicity、本番復旧・電源断耐久性・任意外部ファイルの認証は主張しない。

## 年度横断履歴と合同集計

要求時検証済みviewは次の3streamをyear・record_kind・namespace・match_idで分離する。

|年|種別|対象|
|---|---|---|
|2026|fictional_tournament|保存山梨31試合、元competition scope|
|2027|fictional_practice|保存練習1試合、LAB114:PRACTICE|
|2027|fictional_tournament|今回2試合または保存済prefix、fictional: namespace／LAB116 scope|

`snapshot(practice_store=...)` は同一所有学校年のPracticeStoreを独立RO監査して結合する。
永久player_idで学年／入学年／program／元学校／進級・新入・卒業と、実打席／投球成績を閲覧できる。
新入生の2026未入学、卒業者の2027出場なしを明示する。
合同個人成績はentry teamと元学校の両方を返し、選手の学校を合同IDへ付け替えない。
`team()` の勝敗・順位はentry単位。学校表示の `fictional_team_records` は関連チームの参照であり、
`standalone_wins/losses` は単独entryだけを数える。合同構成各学校は常に単独勝敗0。
BYEは1勝にしない。途中段階に優勝や順位を作らない。
公式2027出場／資格／合同継続／日程／順位はNone、公式確認・製品開始許可はfalseを維持する。

## 検証・運用

`python tests/stage43g116_audit.py --require-windows --json-output <新規report.json>`。
専用13件、skip0必須。自己生成の不変saved31→annual33→practice1出典をclass内で一度だけ作成し、
各testのtargetは独立、毎case後に元3DBのSHAを照合する。元検証自体は各実行で省略しない。
fixture生成時間、case別時間、元3DBのSHA、実行コード8ファイルのSHAと実行前後不変を独立に記録する。
既存Windows年次jobへstepを追加し、新job／OS行列は追加しない。既存111–115の件数／skip条件を保持する。
既存旧17版に真の旧115 mainから自己生成exportしたRO候補を追加して旧18版とする。
catalog338・master106CSV・候補bytes不変、restore／replay非許可を検証する。
全unittest、関東8都県17校E2E、既存Windows native Tk／SQLite・保存・年度履歴も維持する。

実測とCIは別報告書へ記録する。hosted Windows CIと個人PCの目視／サインアウト・再ログイン／OS再起動は区別する。
製品統合、47県シーズン運転、公式情報推定、migration／restore／GC、GUI全面改修、EXE／installerは対象外。
保存イベントは内部oracle証拠であり、製品の全打席ログ恒久保存を新しく必須にする決定ではない。
最終headの全必須CI成功後も新PRは未マージ・auto-merge無効・レビュー待ちで停止する。
