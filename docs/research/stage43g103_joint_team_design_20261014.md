# Stage43G-103 学校と大会チームの分離・停止境界設計

Issue #261、PR #260マージ済み最新main `8480dc079967e12365ccb145860ee2f34243402f`から `stage43g-103-joint-team` を作成。Windows専用・個人利用・非配布。完全Option A、永久選手ID、進行年数に人為上限なしを維持する。

## 公式確認と32行の学校照合

2026-10-14に、山梨県高野連が速報配信責任者である[大会概要](https://baseball.omyutech.com/CupHomePageTop.action?cupId=20260013610)、[出場校一覧](https://baseball.omyutech.com/CupHomePageTeams.action?cupId=20260013610)、[組合せ](https://baseball.omyutech.com/CupHomePageTournament.action?cupId=20260013610)を再確認。概要の32という数だけで構成を推論せず、出場校一覧の全32行を照合した。結果・勝敗・実選手を入力に使わない。

次表の「公式」は一覧に表示された出場チーム名の確認、「照合」は既存マスターdisplay_nameへの対応を意味する。学校ID自体を主催者が認定した意味ではない。略称対応はローカルの照合であり、正式校名の変更を認可しない。行順は確認した出場一覧順で、シード順ではない。

|行|公式表示（確認済）|学校マスター照合（済）|異表記／合同構成|
|---:|---|---|---|
|1|上野原|SCH000222 上野原|一致|
|2|山梨農林・塩山|SCH000202 農林／SCH000220 塩山|合同名を確認、山梨農林→農林は略称照合|
|3|富士学苑|SCH000225 富士学苑|一致|
|4|山梨学院|SCH000216 山梨学院|一致|
|5|北杜|SCH000197 北杜|一致|
|6|吉田|SCH000226 吉田|一致|
|7|富士北稜|SCH000227 富士北稜|一致|
|8|富士河口湖|SCH000228 富士河口湖|一致|
|9|山梨|SCH000219 山梨|一致|
|10|巨摩|SCH000204 巨摩|一致|
|11|日川|SCH000218 日川|一致|
|12|甲府南|SCH000207 甲府南|一致|
|13|甲府城西|SCH000210 甲府城西|一致|
|14|甲府工|SCH000213 甲府工業|略称|
|15|甲府昭和|SCH000201 甲府昭和|一致|
|16|甲府東|SCH000215 甲府東|一致|
|17|甲府一|SCH000214 甲府第一|略称|
|18|甲府西|SCH000209 甲府西|一致|
|19|白根|SCH000203 白根|一致|
|20|笛吹|SCH000217 笛吹|一致|
|21|身延|SCH000206 身延|一致|
|22|都留興譲館|SCH000224 都留興譲館|一致|
|23|都留|SCH000221 都留|一致|
|24|青洲|SCH000205 青洲|一致|
|25|韮崎工|SCH000199 韮崎工業|略称|
|26|韮崎|SCH000198 韮崎|一致|
|27|帝京三|SCH000196 帝京第三|略称|
|28|日大明誠|SCH000223 日大明誠|一致|
|29|日本航空|SCH000200 日本航空|一致|
|30|東海大甲府|SCH000211 東海大甲府|一致|
|31|甲府商|SCH000208 甲府商業|略称|
|32|駿台甲府|SCH000212 駿台甲府|一致|

全32行の学校集合はSCH000196–228の33校と対応し、照合上の追加／不足0。31単独枠＋1合同枠という構成は、この全行照合から確認した。加盟校台帳の完全性や出場資格の法的／公式証明は別問題。

|論点|公式確認|マスター照合|推定／未確認と採用判断|
|---|---|---|---|
|参加構成|一覧32行、合同名1行|33校の対応済|読取の照合。製品参加資格へ接続しない|
|農林・塩山|合同表示確認|202・220の名に対応|独立2校を維持。主催者のIDや合同解散時ルールは未確認|
|欠場|一覧に対応しないマスター校なし|全33校をカバー|欠場なしの正式証明、当日棄権等は未確認|
|資格|一覧に出場表示あり|既存summer_areaと比較|資格審査・合同承認資料・春秋の資格は未確認|
|シード・抽選・BYE|組合せページ存在を確認|現行seed／slotsは空|ページ図の個別枠・シードの確定照合は未実施。生成seedを公式抽選と扱わない|
|日付|会期7/5–7/22、抽選6/24|Stage102カレンダーと一致|個別試合日・順延・合同枠日程は未確認。現行生成日程の公式認定なし|
|結果・登録選手|採取しない|架空生成だけ|現実結果の再現・選手登録ルールの認定なし|

Stage102は33独立校／660人／32実試合／64枠・31BYE。目標の32チームなら31実試合・32枠だが、学校マスターは33校のまま。**本Stageで32チーム31試合は未実施。** 構成資料はそろったが、下記保存・能力契約が成立しないため進めない。

## school_id=team_idの境界と完全A不足

|境界・実コード|暗黙の1学校=1チーム契約|合同化に必要な契約|
|---|---|---|
|models.AnnualCompetitionInput／season／live_season_planner|entrant_school_ids、direct_main_entry、seeds、slot、winner override、plan fingerprintが学校ID|年・大会を含む出場team_id、学校membership、出典fingerprint|
|engine.TournamentEngine／tournament_runtime／main_tournament|学校master存在・同県検証、勝者／champion／rankingは学校|資格検証と対戦枠のID分離。BYE・勝上りはteamで行う|
|school_area・access rules／same_year_regional_feeder_gate|学校IDの集合・上位校を次大会へ送る|合同チームを翌大会の学校資格と同一視しない。今回は未接続|
|game_core.tournament_bridge.AbilityMatchResolver|学校IDで生成・provider・cache・TeamMatchInput。SchoolRoster年／学校一致|正本学校seedと試合team seedを分離する新入力型|
|game_core.players.SchoolRoster|20人、roster_no1–20、全員同校・学年／position契約|学校ロスターは変更せず別登録簿にteam_slotを保存|
|game_core.team_strength.TeamStrengthGenerator|全能力snapshotが1校所属であることを実際に拒否検証|所属を変えず、登録簿からlineup／投手陣生成する新API|
|match_contract／match_simulator|school_idで攻守・投打集計・TeamGameStats。選手statsの学校値も対戦IDを使う|team_idとorigin_school_idの別列。投手処理・相手校の比較をteamで実施|
|career_roster_archive.CareerRosterArchive|学校年ロスター不変。永久identityはplayer_id／学校／入学年|この正本を維持。登録簿は別immutable snapshot参照|
|historical_match_archive.HistoricalMatchArchive|team1/2とteam1/2_school_id、個人学校、team_stats、inningの整合。school検索はteam1/2のOR|参加学校→試合の別indexと登録出典、個人team_id。既存readerの継続保証|
|career_competition_outcomes.CareerCompetitionOutcomes|ranked_school_ids、champion_school_id、source manifest|順位をteam単位で保存。農林単独優勝や両校に重複勝利を与えない|
|career_longitudinal_read／career_player_records／career_history_browse_model、v2 roster attribution・index|学校を対戦側と同一視しSQL集計、個人は永久ID join|学校参加履歴と単独学校勝敗を分ける表示・集計・index version|
|career_history_tk_pilot／yamanashi33_history_tk|学校経路と学校順位、Stage100–102固定plan認可|チーム経路＋構成校選択。合同履歴で単独成績を捏造しない|
|live_game_service Stage100/101/102／legacy_backup_compatibility|学校集合・seed・source・履歴を固定。338入力catalog|新reader/writer版と内容verify先行。現行契約を許可拡大しない|

完全Aにはスコア・イニング・投打／チーム成績・永久IDがあるが、**チーム所属と元学校所属の同時保存、年大会team membership、選抜登録出典、チーム順位、構成校の試合検索indexがない**。打席eventsは既存archiveで全件保管する契約ではなく、現在のOption Aが提供する範囲を勝手に補完しない。現在のschool_idを合同IDへ置き換えると永久identityを損ね、学校名だけでjoinすると同名選手を混同する。

## 今回の最小実装と止めどころ

`joint_team_fixture.py`はwriter・plan・resolverから参照しない独立したread-onlyモデル。固定2026/CMP000041の自己生成4校80人、農林／塩山合同＋帝京第三単独＋北杜単独の**3チーム**を扱う。IDは `FX103:2026:CMP000041:joint/solo1/solo2`、出典は `stage43g103_self_generated_readonly_v1`。学校IDを新規作成・統合・改名しない。

初年度組込みgenerator、学校ロスターseed430103の元正本を再生成照合して受理。school/year／入学年／学年／永久ID／seed／名前の任意変化、同校二重出場、team namespace衝突、学校／正本不足を拒否。正本から凍結Player値を保持し、可変SchoolRosterと返却dictの変更が後のpreviewへ伝播しない。ロスター集合のSHAは出典比較用であり真正性署名ではない。

**選抜は試験用の読取プレビューだけ**。既存POSITION_SLOTSの20枠ごとに構成学校を交互に選び、該当positionで未選抜の最小roster_noを採る。両校10人ずつ、全20人・投手5枠。team_slot1–20は元学校のroster_noとは別。元player_id／school_id／入学年／学年をそのまま表示し、40人同時登録をしない。この規則は公式の登録制限や両校の現実選抜ではない。選抜をSchoolRosterへ再包装すると元roster_noの重複・所属一致で拒否され、能力生成も混在学校を拒否することを実コードで確認した。

`legacy_annual_input()`は無条件に`JointTeamWriterUnsupported`。直接engineへnamespaceを渡してもunknown schoolでMAIN作成前に拒否、resolverへ混在school rosterを渡しても拒否、能力生成器もone-school条件で拒否する。正常な従来fixtureの実6試合を別途進め、保存のSQL/SHA・イニング・個人成績、学校／全選手履歴を照合する。**合同3チームの2試合を実行した証明ではない。** スコア・未実施イニング・順位・学校勝敗をpreviewに生成せず、archived_resultsはNone。

新`joint_team_fixture_tk.py`は同じ3枠→元学校／永久ID／学年／入学年を表示する閲覧専用widget。既存8校demo／33校履歴GUIに取り付けない。native mapped Tkの選択、例外なし、元SQLiteのbytes不変・native close・rename/reopenを検証する。個人Windows PCの目視とは区別する。

## 次工程の保存・読取案

[ADR-037（Proposed・未採用）](../adr/ADR-037-competition-team-school-separation.md)を参照。年／大会のimmutable出場チーム台帳→学校membership→20人登録簿のsnapshot→実試合team_idと元学校player_id→team順位→学校参加履歴の順に別契約を作る。学校別正本と個人identityは現行形式を保持する。合同解散後も過去の年大会membershipと登録簿を全件残す。先に新read-only readerと旧5版内容verify、SQL独立oracleを成立させ、その後新しいopt-in writerを採用する。既存save移行は無断実装しない。

学校別過去記録では、合同の参加試合を両構成校から閲覧できるようにするが、チームの優勝や勝敗を各校の単独勝敗へ複製しない。個人の打撃／投球成績は元学校＋永久IDから検索し、team_idは試合時登録先として併記する。分母となる学校試合数・leaderboardの合同所属扱いを明示仕様にするまで集計しない。

シード・BYE・勝上り、未完了seal、登録簿欠損、途中失敗・部分保存、年次進行・feederは新writerの必須故障検証。Stage103はwriter不認可で止めるため、これらを新合同保存で実行したとは報告しない。JSON／複数SQLite commitは引き続き非原子的。新journal・migration・restore・全国合同一般化・翌年開始・履歴削除・EXE配布を追加しない。

## 互換性と検証

catalog対象編集前（今回は対象編集自体なし）に真のStage102 mainをgit archiveし、別Pythonプロセスで自己生成旧候補export/verifyした。変更後は真の94/99/100/101/102の5checkoutから別プロセスで候補を作り、read-only内容verify・bytes不変を検証。338catalogの**全入力bytes不変**、106master CSVを含むdata集合／bytesも不変。Stage102のcatalog版を維持する。94–101の現行replayは既存と同様拒否。102は既存と同一のruntime入力版で、合同モデルを追加したからreplay権限を与えたのではない。真正性・本番restore認可は別。

Windows Python3.12専用のheadless10件とmapped Tk1件をzero skips gateにする。Stage91–96の既存6workflowにStage103試験のPR pathsを追加し、jobやLinux／Windows matrixを削らず再実行する。Stage94–102既存Windows CI、SQLite lifetime、全Python unittest、関東8都県17校E2Eを維持。Linuxは補助。既存saveは所定rootの件数だけ調べ、内容を使わない。公開artifactには試験集計だけを出し、秘密／絶対path／個別SHA／旧候補内容を載せない。全最終head CI成功後も未マージ・auto-merge無効でレビュー待ち。
