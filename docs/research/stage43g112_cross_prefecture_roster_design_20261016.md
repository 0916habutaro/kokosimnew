# Stage43G-112 学校年度ロスターの県横断契約

起点はStage111 PR #278マージ済みmain `45e9eafe0dc63f0540563d8d32186d2e735b48a4`。指定済みブランチ `stage43g112-cross-prefecture-rosters` を使用する。Windows専用・個人利用・非配布のゲームであり、今回の追加機能は自己所有一時領域の学校ロスター試験に限る。

## 既存契約の棚卸し

|正本・機構|責務|Stage112の扱い|
|---|---|---|
|`game_core/players.py` `SchoolRoster` / `Player`|学校ID/program ID、20現役、永久ID、入学年、氏名、守備/利き手、roster_no。学校ロスターが所属の正本|変更せず再利用。氏名から学校・選手を統合しない|
|`game_core/career_rosters.py` `advance_school_roster`|保存前年度から卒業、進級、卒業枠への新入生補充。隣接年・同seed|共通API内からそのまま呼ぶ。5/7/8は初年度だけ、次年度8/5/7、その次7/8/5|
|`career_roster_archive.py` `CareerRosterArchive`|校年snapshotと永久identityの校別原子追記、冪等、入学年索引履歴|writer/DDLを変更せず再利用。卒業後もidentityと過去snapshotを残す|
|`yamanashi_demo_store.py`|32team/33学校・登録640人と学校660人、保存済み完全A31試合、namespace、lease/pinとRO監査|既存writer・保存形式は変更しない。Stage111の自己生成sourceだけをadapterが読む|
|`yamanashi_tournament_registration.py`|YEAR=2026、seed430103、CMP000041、33学校、32出場team、合同20枠|県大会固有。共通ロスター契約へ持ち込まない|
|`yamanashi_tournament_lab.py`|31試合の進行・封印checkpoint、seed/event/bracket検証|山梨sourceの完了ゲートにだけ使用。長野へ転用しない|
|`yamanashi_annual_rosters.py`|自己生成2026全31完了確認、別DBへの2027学校継承、924人の年別履歴|`_expected`のロスター遷移だけを新共通APIへ委譲。既存schema・lineage・受理JSON・公開APIは維持|
|`CareerHistoryBrowseModel`|製品sealed年度・学校/試合の範囲読取と履歴表示|接続しない。試行を製品sealed年度に見せない|
|`CareerCompetitionOutcomes`|実行済み封印大会に基づく順位/資格|接続しない。合同team勝敗の学校単独成績への複写、未来の資格生成は0件|
|全国学校/硬式program/地区マスター|学校所属と地区構造。大会参加・資格確定そのものではない|実IDと出典を照合して4校だけ選ぶ。data/106CSV・catalog338入力は変更しない|

## 共通APIとsource acceptance

`school_roster_contract.py`は県大会をimportしない。`accept_roster_source`は学校集合・年度・career seed・name-provider recipe・学校ID/program/表示名/県・保存payload SHA・校間永久ID一意性を検証し、`RosterAcceptance`を返す。学校数・県・大会ID・2026/2027・seed430103は共通APIの定数ではない。

`stream_school_transitions`は保存学校ロスターをID順に1校ずつ読み、receiptの学校/年/seed/recipe/保存SHAを照合し、既存`advance_school_roster`へ渡す。全streamを消費した時点で学校集合の完全性を検証する。途中prefixを年度受理と解釈することは禁止。recipeは現在の `placeholder_v1/career_roster_v1/player_career_newcomer_v1` のみ許可し、未知providerを黙って採用しない。今後の人名provider追加には別の版と照合規則が必要。

進級者は学年だけ+1し、永久ID・元学校/program・入学年・氏名/name_source・roster_no・守備/利き手・generation_seedを保持する。卒業者は現役から除外し、保存履歴は保持。新入数/枠は前年度保存rosterの3年生から算出し、毎年の初年度比率強制や翌年seedでの全員再生成を拒否する。全校と翌年のID重複、archiveの既存卒業生ID再利用も拒否する。

`RosterSource.snapshot()`が再利用可能なsource acceptance interfaceである。

|adapter|入力・受入根拠|認可しないもの|
|---|---|---|
|`VerifiedSavedSchoolSource`|Stage111 `SelfCreated2026.verified()`による保存31試合/33学校/660永久ID・marker・SQL・SHA・seed/event/bracket照合。receiptへsource契約hashを結ぶ|別県の大会完了、2027大会・製品年度の開始|
|`MasterRosterSandbox`|repo実学校の少数明示IDから自己生成する学校20人×4校。固定fixture年度2026・seed430112。snapshot毎にrecipe/保存payloadの整合性を再照合|2026長野大会結果・公式出場校・秋枠・日程の存在や完了|

receiptのSHAは整合性の根拠で、認証済み出典の証明ではない。全sourceを `scope=roster-only trial` / `season_start_authorized=False` と表現する。大会完了ゲートはadapter自身の責務であり、共通関数が31試合や大会IDを推定することはない。

## 別県の実マスター照合

repo `data/master/schools.csv` / `baseball_programs.csv` / `sources.csv` と `data/areas/school_area_memberships.csv` を照合した。

|県|学校ID|program ID|学校名|学校/硬式programの出典|
|---|---|---|---|---|
|長野20|SCH001636|PRG001636|飯山高等学校|SRC000067|
|長野20|SCH001637|PRG001637|下高井農林高等学校|SRC000067|
|長野20|SCH001638|PRG001638|中野立志館高等学校|SRC000067|
|長野20|SCH001639|PRG001639|中野西高等学校|SRC000067|

SRC000067はrepo記録の「2026年度 長野県高等学校野球連盟 加盟校名簿（硬式82校）」、照合日記録2026-10-02、URLは <https://www.nagano-hbf.jp/wp_hbf/wp-content/uploads/2026/04/2026_kameikou.pdf>。今回の確認はrepo記録の照合で、外部PDFの再取得・2027更新確認ではない。

4校とも2026 `ASM000021/AREA000032`（都府県代表区分、SRC000241）と `ASM000053/AREA000075`（北信支部、SRC000067）を持つ。前者は大会不参加校も含む所属属性、後者は2026名簿の支部別掲載に基づく。いずれも2027公式出場資格や日程へ変換しない。fixtureは高校4校に限定し、高専の年限は対象外。4校の表示名はrepo内で他IDと一致しないことも確認した。同名別県の実学校ペアは島根32/SCH000342/PRG000342（SRC000079）と三重24/SCH000398/PRG000398（SRC000071）の「飯南高等学校」。別試験で氏名や表示名によるID統合を拒否し、2031→2032・seed99112も確認する。山梨33校と長野4校を同seed430103の37学校集合として共通streamへ渡す追加照合でも、旧現役740＋新入296の1036永久IDを重複なく保持する。混合receiptでも長野大会の完了認可は与えない。

## 隔離保存と閲覧

`SchoolRosterTrial`は空のlive `TemporaryDirectory`所有者とopt-inのみを受け取る。任意SQLiteパス、既存save、旧backup候補の採用APIはない。山梨sourceとtargetの親子/同一rootを拒否する。

Stage111から既存Windows pin・lease・実体ID・link/reparse/hardlink/未知ファイル/DELETE-header/sidecar検査・明示closeを再利用する。学校ロスター保存は既存 `CareerRosterArchive.save_initial_roster` / `advance_and_save` のみ。新DBの2つの試行テーブルを含め全表はUPDATE/DELETE拒否で、保存全SQL行・schema・integrity・校年payload・永久identityをRO監査する。監査中に保持した検証済みpayloadからdetached browse結果を作り、監査後に未検証のDBを別接続で再読しない。

校別commit後の正常prefixは同capability/同sourceで別プロセス再開可能。全校が揃い、全件一致を確認してから別の1DB transactionで年度ロスター受理を追記する。部分年度・異source/seed/recipe・年飛ばし・学校欠損・偽受理・未知schema・二重所属・永久ID衝突を拒否する。確定前故障はrollback、確定後ACK喪失は冪等再試行。dirty/hot journalはSQLite接続前に拒否し修復しない。

原子性は「校別追記の1 transaction」と「全対象校受理の別transaction」。複数DB間の原子性、任意の媒体障害からの自動復旧、初期化途中のDB採用は保証しない。

`browse`は2026/2027の学校payload、卒業/進級/新入人数、範囲と資格未承認を返す。卒業生は `CareerRosterArchive.player_history` で元学校・入学年索引から最大3年度の過去snapshotを読む。山梨の従来 `AnnualRosterView` では31試合の過去完全Aも継続参照可能。合同2校を1校へまとめず、勝敗はteamのまま、学校単独勝敗はNoneである。長野trialは両年度とも試合0件、出場team/成績0件。

読取実例は `python examples/stage43g112_roster_only_read.py --self-created-only`。県/4学校/2026・2027の学年別人数と卒業32・進級48・新入32を出す。新GUIは設けない。

## 性能・長期運用

学校単位の遷移は現役20人だけ。全体の一意性検証にID集合・校別receipt索引を保持するが、全学校のPlayerオブジェクトを共通stream内で保持しない。少数校trialの監査は固定2年度の全件照合であり、製品の長期照会の代用ではない。

1校で50/100/200回進級し、51/101/201学校snapshotと全永久identity、各年20人、最古選手の過去履歴を確認する。保存済み前年度からのみ更新する。永久選手履歴は既存(school_id,year)索引と入学年範囲を使用する。試合生成・ゲーム年度開始は0件。

1000校の別の構造ロスターstream probeでは、自己生成学校rosterを1校ずつreceiptへ送り、再び1校ずつ共通遷移を消費する。これは保存された実ゲームの読み出しや数千校のSQLite同時展開ではなく、ロスター構造だけの時間/メモリ計測である。実測値は報告書に記す。次段階は保存済み校年索引から同streamへ入力し、100→1000校のDB追記・衝突索引・受理時間を分離測定してから拡張する。47県シーズン一括実行、過去大会の毎年再生成・GCを行わない。

## CI・互換性・非対象

既存Stage111専用Windows Python3.12ジョブへ新10件/skip0 auditを追加し、CIを増殖させない。Stage111の従来8件/skip0、Stage109/110の保存/再開・native Tk、既存必須gateの件数とskip条件は維持。Stage91〜96の保存境界CIには新ファイルの発火pathを追加するだけ。全unittestと関東8都県17校E2Eを実行する。

旧Stage94/99/100/101/102/103/104/105/106/107/108/109/110/111の14版は真の旧main commit checkoutから自己生成した候補をRO内容verifyする。新試験は旧111(main `45e9eaf`)を追加し、catalog338とmaster106CSVの一致、原本bytes不変、replay許可/内容整合/真正性の区別を確認する。製品catalog対象変更はない。

全国GUI、2027公式大会日程/出場資格・合同継続・秋枠の推定、別県実試合結果、CompetitionRun/製品HistoricalMatchArchive/未来CareerCompetitionOutcomes接続、製品writer移行、既存slot上書き、restore/import、履歴削除/GC、EXE/installer/配布は対象外。本人のWindows手操作・サインアウト/再ログイン・PC再起動は未検証。CIの別Python再開でOS再ログインを証明したとは扱わない。

PRは必須CI成功後も未マージ・auto-merge無効・レビュー待ちで停止する。
