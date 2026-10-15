# Stage43G-108 山梨夏32チーム・33校の段階実行設計

Issue #271。PR #270マージ済みの最新main `a657960afbf00d3fbd2f7c091532a0ba647347a2`をfetchし、`stage43g-108-yamanashi32-tournament`を作成。Windows専用・個人利用・非配布ゲームの独立lab。製品writer採用ではない。

## 出場構成の根拠とimmutable学校正本

[Stage103の公式32行照合表](stage43g103_joint_team_design_20261014.md)を根拠とする。公式出場一覧の表示名と既存学校IDのローカル対応であり、学校ID・抽選順・出場資格の主催者認証を意味しない。Stage103が確認した資料は[出場校一覧](https://baseball.omyutech.com/CupHomePageTeams.action?cupId=20260013610)と[大会概要](https://baseball.omyutech.com/CupHomePageTop.action?cupId=20260013610)。今回、実勝敗・実選手を取得しない。

|確認行|公式表示|既存school ID末尾（SCH000以下）|新team ID末尾|
|---:|---|---|---|
|1|上野原|222|SCH000222|
|2|山梨農林・塩山|202 農林、220 塩山|joint|
|3|富士学苑|225|SCH000225|
|4|山梨学院|216|SCH000216|
|5|北杜|197|SCH000197|
|6|吉田|226|SCH000226|
|7|富士北稜|227|SCH000227|
|8|富士河口湖|228|SCH000228|
|9|山梨|219|SCH000219|
|10|巨摩|204|SCH000204|
|11|日川|218|SCH000218|
|12|甲府南|207|SCH000207|
|13|甲府城西|210|SCH000210|
|14|甲府工|213 甲府工業|SCH000213|
|15|甲府昭和|201|SCH000201|
|16|甲府東|215|SCH000215|
|17|甲府一|214 甲府第一|SCH000214|
|18|甲府西|209|SCH000209|
|19|白根|203|SCH000203|
|20|笛吹|217|SCH000217|
|21|身延|206|SCH000206|
|22|都留興譲館|224|SCH000224|
|23|都留|221|SCH000221|
|24|青洲|205|SCH000205|
|25|韮崎工|199 韮崎工業|SCH000199|
|26|韮崎|198|SCH000198|
|27|帝京三|196 帝京第三|SCH000196|
|28|日大明誠|223|SCH000223|
|29|日本航空|200|SCH000200|
|30|東海大甲府|211|SCH000211|
|31|甲府商|208 甲府商業|SCH000208|
|32|駿台甲府|212|SCH000212|

全team IDは`LAB108:2026:CMP000041:`を接頭辞とし、学校IDとは別namespace。上表の学校集合はSCH000196–228の33校、重複・不足0。加盟校マスターや地区区分を変更しない。`yamanashi_tournament_registration`は既存generatorで33校×20人の正本を生成し、660永久ID・元学校・入学年・学年・position・roster_noを毎検証時に再生成照合する。

出場登録は32×20＝640枠という**ゲーム用仮定**。単独31校は全20人。合同はStage103/104と同じposition別交互選抜・未使用最小roster_noにより10＋10人。学校正本の残り20人も保持する。team_slotは元roster_noと別。学校membershipの二重所属、player重複、欠落、未知ID、team衝突、scalar型差、異年度／seed／選抜改変をfail closedする。校名でjoinしない。

|出典|固定値・意味|
|---|---|
|学校正本seed|430103、既存のPlayerRosterGenerator。永久IDのrecipeを維持|
|能力seed|430103、旧`_team_input`の学校別能力snapshotと打順・投手順を明示再利用|
|選抜seed|430108、位置indexとの剰余で交互学校を選択するrecipeに記録。公式比率ではない|
|ブラケットseed|430108、専用Randomで出場IDリストをshuffle。公式抽選を意味しない|
|試合seed|Gate Bは108001–108007、Cは108101–108131。全試合固有|

## 既存コードの固定境界

Stage104–107設計・報告、ADR-037–040および実コードを確認した。

|旧ファイル／固定前提|維持する契約|新しい入口|
|---|---|---|
|joint_team_fixture|4校80人、3team preview|別33校登録factory。旧ENTRIES/SCHOOLSは変更しない|
|joint_team_registration_lab|3team、LAB104 match1、430104、能力430103|既存RegisteredPlayer/Team/TeamInputと能力生成だけ再利用。AnnualRegistration/AnnualMatchInputを別型で追加|
|registered_match_driver|旧公開simulateは104validator固定|新validatorの検証後に内部`_run`を明示利用。旧公開APIへ新型を渡さない|
|registered_full_a_contract/oracle|v1 team/元学校/永久ID、完全Aとevent再集計|結果型と独立event oracleを継続。match IDの書換えや型偽装なし|
|registered_full_a_lab_store|旧_matchと固定1試合seed、8表exact reader|DDLの8表のみ再利用。新writer/reader/filename/version、全登録・plan・結果を新factoryから再構成|
|joint_tournament_lab/oracle|固定3team・BYE1・2試合、旧seedと結果SHA|専用8/32team planと独立oracleを別ファイルへ追加。旧planを一般化しない|
|joint_tournament_store/tk|11表、1/2/3の一意順位、2試合完了|別storeとTk。新team_ranksはteam ID primary key、同順位と到達roundを保持|

製品LiveGameService/TournamentEngine/HistoricalMatchArchive/save schemaと338catalog入力を変更しない。データ集合・106CSV不変。ADR-037–040はProposedのまま。

## Gate A/B/C、planと進出oracle

Gate Aは33校660人・32枠640登録と、BYEなし16＋8＋4＋2＋1＝31枠のdry-run。Gate Bは同一登録正本の先頭8team（合同を含む）を専用shuffleして4＋2＋1＝7試合、3ラウンドを計算。残る学校正本と登録も削除しない。Gate CはB成功後に別の新規所有DBで32枠31試合を計算する。B結果をCへコピーしない。

AnnualTournamentPlan v1は年／大会・登録SHA・gate・bracket seed・全出場ID・全match ID／sequence／round／slot／架空day／固有seed／両側sourceをfingerprint化する。match入力はplan SHAと**全保存prefixの結果SHA台帳SHA**も含む。32枠はr1:m01–16、r2:m01–08、r3:m01–04、r4:m01–02、r5:m01。8枠はB namespaceで別ID。試合日は7/5・7/9・7/13・7/18・7/22。確認済み会期7/5–22内の**架空日付**で、個別公式日程・順延は保証しない。Bは先頭3日を用いる。

対戦入力は前round全件のcommit済み実勝者からのみ解決。round-major順のimmutable prefix以外は拒否する。独立`yamanashi_tournament_oracle`はfactory・driver・乱数・SQLに依存せず、roundごとの対戦source・順序・実スコア勝者・敗者の再出場拒否・進出台帳・順位を照合する。各試合は独立event oracleと同seed実行全内容比較で確認する。優勝・スコアの事前注入や学校IDすり替えをしない。

順位は優勝1位・決勝敗者2位・準決勝敗者2teamは同3位、以下同5位/9位/17位。別の順位決定戦を実行していないため厳密1–32位を生成しない。勝敗はteam単位で計算し、元学校へ合同勝利・優勝を複製しない。

## 保存、再開、故障と読取

親が生存中の自己所有TemporaryDirectoryからだけO_EXCLで新DBを作り、登録・33校正本・640登録・planを初期transactionで保存する。明示opt_in=Trueが必須。resumeは同型のcapabilityに含むdirectory/fileのdev/inode一致を検証する。信頼された同一fixture内の権限受渡しであり、署名や製品restore権限ではない。親が所有者を維持したままspawnプロセスを0→1、1→初round終了（B4/C16）、round境界→完了（B7/C31）でそれぞれ終了する。別workerは同じDBをRO再検証後に残りを計算する。所有者cleanup後の再開を拒否する。

BEGIN IMMEDIATEで全旧行・seed/eventを検証し、次入力・新結果・進出を検証して同transaction内に完全A、入力、学校参加index、勝者台帳を追記。最終試合時に全team順位を追記する。全11表UPDATE/DELETE禁止。全内容同一の再追記はno-op、異内容は拒否。各requestでexact schema/trigger・integrity/FK・JSON/SHA・固定正本・全結果seed/event・plan/順位を全照合し、学校参加は独立membership SQL joinでも確認する。検証済みsnapshot内で能力と描画を共有するが、DB読取の検証を省略する永続キャッシュは導入しない。

|故障境界|確認する可視状態|
|---|---|
|計算前・試合前|次試合は実行／commitされず、旧prefixのみ|
|matches/学校index/進出/順位insert後・commit直前|rollback、旧prefixとbytes、順位なし。再試行可能|
|commit後応答前|実commitは保持。同一再追記はno-op|
|旧checkpoint・前round未完・異結果/seed/team|次追記せず拒否|
|exclusive lock / DELETE・WAL|writerはcloseして拒否。WAL readerはcommit済みprefixのみ|
|同時同一append|1件のみcommit、他方は検証後no-op|
|round境界でdirty spill後強制終了|hot journalをRO readerが復旧せずbytes不変で拒否。自己所有fixtureだけ明示recoveryし旧prefixへ復帰して再試行|
|登録欠落・index/plan/入力/結果改ざん、再SHA済み改ざん|読取拒否、修復／移行しない|
|未知schema・不在・file実体交換・所有者消滅|拒否。writerをpathから復元しない|

原子性は**単一SQLiteの試合単位**だけ。31試合全体、JSON＋複数製品DB、OS／媒体故障の原子性ではない。SHAは整合性であり真正性署名ではない。

team履歴は実試合と勝敗・同順位、school履歴は当時の参加teamと試合、player履歴は永久ID＋元学校と実出場投打行／計数累計を返す。全660人を照合し、ベンチ・合同未登録に架空出場を与えない。bulk historyは1回の完全検証snapshotから全員分を返す。率を加算しない。全結果を保持し、履歴削除／GCや進行年数上限を追加しない。ただし実証は2026固定で、TemporaryDirectory寿命後の製品永久保存は未対応。

専用readonly Tkは32team選択、順位・勝上りの縦横scroll、学校／永久ID・試合・全イニング・試合別／累計を日本語で表示し、合同未登録者も選択できる。読取前に旧表示を消し、未完了・破損・navigation読取失敗時は全表示／選択肢を消去する。SQLite native connectionは描画前にclose。正式全国GUIや製品saveへ接続しない。

## 回帰と受入

Windows Python3.12専用headlessはGate A/B/C・故障・旧10版候補の19 tests、native mapped Tkは1 testをskip0必須とする。33/660/640・試合数・経過秒・DB bytes・保存行数を集計JSONへ出す。既存Stage91–107の17workflowに新Stage108を加える。Stage91–96のpath filterへ新labを追加し、既存ジョブを維持する。全Python unittestと関東8都県17校E2Eを維持。Linuxは補助、個人Windows PCの目視手操作は別区分。

旧Stage94/99/100/101/102/103/104/105/106/107の真のmainをgit archiveした独立checkoutから別プロセスで自己生成exportし、現readerでRO内容verify／原本bytes不変を確認する。現コードreplay可否、真正性、本番restore認可とは別判定。実ユーザーsave・候補は利用しない。旧互換suiteは既存保障のため維持する。重複生成の整理は共有fixtureの独立性を別Stageで確認する案だけを残す。

Stage105独立driverは旧MatchSimulatorの確率と投手BF上限式の部分利用。確定塁数進塁、失策/野選重みは通常アウト、犠打/犠飛/盗塁等は未対応、疲労・怪我は試合間未接続。旧製品と同一ルールでも公式結果再現でもない。30回同点・打席上限なら結果なしで停止し、固定勝者を入れない。

既存save変更、本番restore/import/activation、製品writer/schema統合、2027開始、全国合同一般化、正式全国GUI一括実装、EXE配布は対象外。Gate C不可なら実達成件数と原因を報告する。最終head全必須CI成功後も未マージ・auto-merge無効でレビュー待ち。
