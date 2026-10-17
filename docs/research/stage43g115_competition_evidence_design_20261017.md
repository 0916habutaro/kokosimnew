# Stage43G-115：2027大会証拠ゲートと架空dry-run

2026-10-17。Issue #285。起点はPR #284マージ済main
`8cf1c4324730d2ec4e24aa41728fc626b16d014d`。
指定ブランチ `stage43g115-2027-competition-evidence-gates` を使用する。

## 現行入力の棚卸し（実装前に確認）

|既存入力／実体|受理できる契約|2027年大会に不足するもの|
|---|---|---|
|`data/competitions/competitions.csv`|大会ID・2026参照年・種別・学校数・構造出典|2027年度の実参加team集合。IDは構造参照に限る|
|同 `competition_stages.csv`、stage format/transition群|MAIN、予選、進出数、組合せ構造|2027枠数・予選免除・実際の組合せの確認|
|`data/schedules/2026/season_calendar.csv`、`competition_stage_calendar.csv`|2026試合日・draw日・primary_source_id|2027年の公式日程出典。日付の年置換は禁止|
|`data/areas/school_area_memberships.csv`、`baseball_programs.csv`、`schools.csv`|学校／program／所属区分、2026 reference_year|対象2027の地区所属・適用rule version|
|`data/competitions/prefecture_region_memberships.csv`|県と地区の関係|年度別team出場枠を確定しない|
|`competition_access_rules.csv`、`competition_seed_rules.csv`、`qualification_rules.csv`|前年秋→春、夏→秋等の進出・免除・シード規則、source_year_offset・effective年・出典|規則の将来年適用確認と、対象前段大会の真正な保存結果。effective_to空欄だけで2027公式確認済にはしない|
|2026県大会・地区予選資料と `yamanashi_tournament_registration.py`|明示された2026山梨33学校／32team／合同1、登録640と学校660永久IDの区別|2027の参加エントリー、合同継続、構成員、資格。2026登録をコピーしない|
|`CompetitionRun`|実行済stage・match・outcome|未実施2027大会の根拠はない|
|`CareerCompetitionOutcomes`|sealed年度の保存ledger SHA・全MAIN試合・全順位一致が必要|次年度blueprintが解決しても `live_runtime_ready=False`。学校ロスターだけで結果を作らない|
|Stage110/111の自己生成保存31試合→保存2027学校年|33校660現役、卒業264・進級396・新入264、永久ID924|大会資格・合同・公式カレンダーは未確定|
|Stage113保存100校 roster-only|山梨33＋長野33＋静岡34の学校年受理|前年度大会完了の証拠なし。大会資格へ昇格しない|
|Stage114 `PracticeStore`|別DBの2027架空練習試合1、年／record_kind／ID別の履歴|公式参加・シード・日程・順位の根拠にならない|

## 年度別入力と証拠境界

新規 `phase2_engine/competition_evidence_gates.py` は製品writer/schemaを変更しない独立読取API。
`dry_run(AnnualRosterLab, CompetitionRequest, fictional_opt_in=True)` は各呼出しで
Stage114 `saved_authority` を通し、所有capability、保存全31試合の監査、学校年の全33校受理、
SQL保存2027 JSON、永久ID系譜、元DB bytesを再照合する。browse表示や再生成ロスターを入力にしない。
既存監査内の保存2026試合の再計算照合は維持するが、新しい2027試合は生成しない。

|独立実体|入力と検査|結果フィールド|
|---|---|---|
|保存学校年（既存所有アダプター）|year=2027、33学校正本・660現役・924永久ID|`roster_year_accepted`|
|保存前年大会（既存所有アダプター）|全31試合・保存結果／封印／系譜を再監査|`prior_sealed_year_checked`|
|`EntrySet` / `EntryTeam`|大会ID・対象年度・大会種別・namespace、entry_team_id、学校/program集合、登録20永久ID／team|`entry_set_checked`|
|`JointComposition`|明示的な複数学校/program構成。単独校との二重出場拒否|`joint_composition_checked`|
|`Qualification`|全teamについてexplicit_scenario又はsaved_prior_year、免除bool。後者は保存元receipt SHA完全一致|`qualification_checked`|
|`DistrictRules`|2027 Evidence＋rule_version、district_id、全program所属の重複なし完全一致|`district_rules_checked`|
|`SeedRules`|別出典・rule_version、明示したシード順位。空tupleはシード無しの宣言、欠落は未確定|`seed_rules_checked`|
|`DrawRules`|single_elimination、参加枠数、2冪bracket、bye数。枠／team数不一致拒否|`draw_checked`|
|`Schedule`|独立出典と2027の厳密ISO日付。round数分の昇順・重複無しの宣言日。試合割当は作らない|`schedule_checked`|

各実体の `Evidence` はauthority Enum、対象年、source、recipeを持つ。
学校ロスターと前年保存証拠にも別digestを付け、7契約と合わせ9個のcanonical SHA256、
全request SHA、検証RECIPEを返す。digestは改ざん比較用で公式認証ではない。

各欠落は `entry_set:missing_evidence` 等、整合性拒否はゲート名＋理由を列挙。
他ゲートの部分成功を保持するが、登録失敗なら登録依存ゲートも失敗し、draw失敗ならscheduleも失敗。
不正な保存元／対象年は受理前に例外で拒否する。部分受理で開始を解放しない。
卒業済・未知・他校の選手、永久ID重複、学校/program/team重複、合同構成員の登録不在を拒否する。

## 架空と公式の二段階

`fictional:` namespaceかつbool `True`のopt-inを両方要求する（1や文字列は不可）。
受理アダプターが存在するのは `Authority.FICTIONAL_DECLARATION` のみ。
`HISTORICAL_CONTEXT` と `OFFICIAL_CLAIM` は受理しない。sourceに公式URLや「verified」を
書いても公式受理実体にはならない。現段階にofficial authorityを発行するAPIは存在しない。

全整合性が成立した場合だけ `fictional_scenario_ready=True`。
`official_year_verified=False` と `product_season_start_authorized=False` は常に独立して維持。
公式entry／合同／qualification／district／seed／scheduleの未確定理由を常に返す。
2026公式規則を将来年へ適用するには別の年度適用根拠が必要であり、本実装は公式認証を代行しない。
Stage113 roster-onlyとStage114練習試合の実体はこのAPIの保存学校年authorityとしても拒否する。
練習試合が存在しなくても本来の入力契約は学校年と大会契約であり、練習試合結果への依存はない。

## 最小縦slice・保存安全性

自己所有TemporaryDirectoryでのみ生成した保存31→受理2027→別DB練習試合1を使用する。
実master上の帝京第三、北杜を単独候補、山梨農林・塩山を明示的な合同候補に利用し、
3team／4枠／bye1／架空seed1／宣言日2を照合する。2026の32team集合は転用しない。
架空候補の選択は2027公式参加や合同継続の主張ではない。
APIには任意save/backupパス、slot指定、restore/replay、書込先引数を設けない。
2027大会試合・公式出場一覧・順位・公式カレンダー生成は0件。
検証対象の2026架空大会と2027架空練習試合のyear／record_kind／match IDと履歴を維持する。

元DB／marker／namespace、学校年DB、練習試合DBのbytes pinを全case後に照合。
catalog338とmaster106CSVも一致検査。既存ルートID・file ID・hardlink・junction・sidecar・
hot journal・lease・明示close・拒否後不変・冪等性のStage100–114ゲートは削除／skip追加しない。
新APIからもsidecar／hardlinkのSQL接続前拒否、partial年度拒否、native SQLite明示closeを検査する。
新規DB／transactionは導入しない。既存の複数DB操作を原子的とは呼ばない。

## 検証運用・Stage116への接続条件

`python tests/stage43g115_audit.py --require-windows --json-output <未作成report.json>` が
自己生成試験CLI。Windows Python3.12で12件・skip0を強制し、公式確認とは別に報告する。
全unittestと関東8都県17校E2E、既存Windows native SQLite/Tk／別process再開を保持。
旧94/99/100/101/102/103/104/105/106/107/108/109/110/111/112/113に
真の旧114 mainを追加し計17版の自己生成候補をRO内容verifyする。旧コードは隔離fixtureを生成する
別process内でのみ実行し、候補のrestore/replayや候補内コード実行をしない。

負荷削減として新規ゲート全caseは1組の不変保存31／2027／practice fixtureを共有する。
既存Stage114 fixtureは破壊・crash・再開試験が同居しているため跨いだ共有は行わず、既存の監査件数を保持。
実測で固定fixture準備とdry-run検査を分ける。未監査cacheや受理flagの再利用による省略はしない。

Stage116では少なくとも、①namespace／RECIPE／全digestの再検証、②架空専用の試合ID・
record_kindと別DBのwriter契約、③全sourceの読取寿命と中断再開、④合同のorigin_school帰属、
⑤資格・seed・免除を反映するdraw処理、⑥rollback／冪等性／独立oracle、⑦公式履歴への混入防止を要する。
本レポートのboolを試合開始capabilityとして渡してはならない。
公式対応は別途、実2027資料の受理・年度適用確認と製品開始の明示承認契約が必要。
個人PC目視・サインアウト再ログイン・PC再起動はhosted CIと区別し未検証として報告する。
PRはCI成功後も未マージ・auto-merge無効でレビュー待ちにする。
