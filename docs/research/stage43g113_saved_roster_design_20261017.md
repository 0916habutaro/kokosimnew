# Stage43G-113 保存型100校年度継承設計

## 対象と前提

Issue #281。開始点はPR #280マージ済みmain `6c3c9e236ef54163be80b066cf64b81f592f0531`。
作成済み `stage43g113-cross-prefecture-100school-rosters` を使用する。
学校は実在マスター、選手は架空。自己所有の空TemporaryDirectoryへの明示opt-in試験である。
任意の既存save/backupパス・製品slot・本番migration/restoreは受け付けない。

## 実装前の棚卸しと証拠境界

|既存構造|入力・出力・今回の境界|
|---|---|
|RosterAcceptance / accept_roster_source|完全な宣言学校集合・seed・recipe・校別digestを照合。学校年度の整合性のみ|
|stream_school_transitions / advance_school_roster|同じ共通APIで保存前年度→翌年度。毎年度初期5/7/8を再生成しない|
|MasterRosterSandbox|生成fixture。Stage112の長野4校・in-memory1000校は保存正本の証明ではない|
|SchoolRosterTrial|前年度コピー、校別CareerRosterArchive transaction、全校確認後の別acceptance transaction|
|VerifiedSavedSchoolSource / Stage109–111|山梨32team/33school/31試合の完了根拠を山梨adapterのみで検証。今回の100校sourceへ流用しない|
|CareerRosterArchive|school_id/year主キー、永久profile・entry_year、学校年度索引。writer/schema変更なし|
|CareerCompetitionOutcomes等|既存封印・Option A全履歴を保全。roster-only年度受付から書き込まない|
|SavedSchoolRosterSource（新規）|生成は作成時のみ。実保存後のSQLite行をdecode、全行/profile/schema・bytes・masterを照合して正本を返す|
|SavedSchoolRosterTrial（新規）|保存source専用入口。既存校別追記・再開・年度受理を継承し、校/年度/永久IDでRO検索|
|competition_start_gate（新規）|独立した大会許可判定。完全ロスターでも常に未許可、未日程・未試合|

## 100校の実マスター照合

2026学校ID昇順で山梨全33校、長野82校中33校、静岡108校中34校を明示選定。
山梨 `SCH000196`–`SCH000228`、長野 `SCH001636`–`SCH001668`、静岡 `SCH002462`–`SCH002495`。
学校ID100・硬式program ID100・地区所属200行の一意性、active・2026年・県コード、
area/scheme所属、学校/program/所属/地区の出典IDとURLを再照合する。
校名をIDにしない。同名別IDはマスター監査出力に列挙し、Stage112の県横断同名試験も維持。
合同校は学校別20人を保持し、大会team枠とは結び付けない。
詳細は `audits/phase2/stage43g113/master_selection_20261017.jsonl`。
全国マスター106 CSV、旧catalog338入力のbytesは変更しない。

## 保存・再開・確定

1. 独立した空の自己所有source領域で2026初期20人×100校を実際にSQLiteへ保存する。
2. root/file/lease identityとSQLite最終bytes SHAをcapabilityに固定する。source全行と永久profileをRO照合する。
3. 別の自己所有target領域へ保存正本をコピーする。同じルート・親子領域を拒否する。
4. 保存済みtarget前年度行からのみ校別transactionで2027を追記する。永久ID衝突時は校全体をrollback。
5. 中断状態は学校ID順prefixのみ。1/50/100校commit直後にos._exitし、親が所有するcapabilityを私有JSONで別processへ渡す。
6. 全100校の保存行・永久profile・正本receiptを照合後、別transactionで年度を受理する。
7. acceptance前の例外はrollback、commit後process終了は冪等再開。hot journalはSQLite接続前に拒否し自動修復しない。
8. 未確定の2027はbrowse/school/playerを公開しない。完了後もsource SHAを維持する。

SQLite transactionの原子性は校別と受付それぞれに限る。sourceとtargetの複数store間は非原子的であり、
前後のSHA・receipt再照合による整合性検査である。認証された外部出典や本番復旧機構ではない。
ファイル差替・hardlink・未知sidecar・hot journalを接続前に拒否し、Windowsではpin/leaseを明示closeする。
close後のrename→復元→SQLite reopenでnative handle解放を確認する。

## 大会開始との分離と次stageの確定入力

ロスター確定は `rosters_accepted=True`、大会開始は常に `season_start_authorized=False`。
`tournament_status=not_scheduled_not_played`、matchesは空、学校単独の大会成績はNone。
ユーザー入力の許可フラグを渡してもroster-only gateは許可に変わらない。
2026山梨の31架空試合完了は他県の2026完了・2027公式資格を意味しない。

|次stageに必要な確定入力|構造上の障害・導線|
|---|---|
|年度別の大会参加program/team、合同校継続|学校ID集合だけでは大会team枠・合同資格を確定できない。別のentry契約が必要|
|県/地区予選資格・進出条件・順位/シード|前年度ロスターに結果・資格根拠がない。大会別qualification receiptとrun gateが必要|
|年度別地区登録・ルール版・欠場/廃部|2026 masterを2027確定値とみなせない。対象年度入力と出典を別受理する|
|日程・会場・休養/重複制約|学校年度受付に日程生成権限はない。確定entryと規則を用いる独立工程が必要|
|大会開始→試合→封印結果|上記gateを通過した架空ゲームrunに限定。架空結果を実在公式資格と呼ばない|

## 検証とCI負荷

新規9保存試験＋真の旧Stage112 main由来export1件＝10件をWindows Python3.12でskip0実行。
既存Windows年次ジョブに追加し、新しいOS行列やジョブは増やさない。
既存Stage111/112・長野1校の長期50/100/200年学校ロスター試験・native Tk・全unittest・関東17校E2Eを保持。
長期ロスター試験は200年の完全試合履歴実績ではない。
既存14版＋新規Stage112で旧15版RO内容verify。旧候補の内容一致とreplay/restore許可は別である。
Stage112候補は変更前のmainから自己生成して固定済み。catalog対象コードを編集しない。

Windows実測は専用監査JSONとActionsログを正本とする。Linuxは補助。
初回source保存、targetコピー、検証/進級/受理、別process再開、全2800人RO履歴検索、DB bytes、
tracemallocとOS process peak RSS、SQL索引利用を記録する。RSSはPython process全体のhigh-water mark。
共通検証は各操作で線形走査し、校別commitごとに全100校を再検証するO(N²)方式を採用しない。
同OSジョブ内の段階別実時間を比較し、将来は同一不変sourceの検証結果共有を検討する。
試験対象・失敗注入・旧版数を減らさず、重複した生成/検証だけを独立比較してから削減する。

個人Windows PCの手操作・サインアウト/再ログイン・OS再起動・既存ユーザーsaveは未検証。
全必須CI成功後もPRは未マージ・auto-merge無効のレビュー待ちで停止する。
