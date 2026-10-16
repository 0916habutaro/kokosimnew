# Stage43G-111 2026→2027学校ロスター継承設計

## 適用境界

起点はPR #276マージ後のmain `b3d2e31ef90bc2924f576e3d69c44044a050a218`。
2026年山梨夏の**ゲーム内架空大会**32チーム・33校・660永久選手・640登録枠・31試合だけを完了判定する。
現実の2026年大会結果や登録選手を表すデータではない。
新規モジュール`yamanashi_annual_rosters`は自己生成した一時試験専用。既存デモnamespace、製品save/backup、任意SQLiteパスを入力にする公開APIは設けない。
Stage109/110のwriter、marker、schema、保存先選択、正式全国GUI、catalog338入力、data/106master CSVは変更しない。

## 既存契約の棚卸しと再利用

|既存機構|既存の責務・今回の扱い|
|---|---|
|`Player` / `SchoolRoster`|永久ID、元学校/プログラム、入学年、氏名、守備位置、利き手、roster_noを持つ。初年度学年5/7/8人、現役20人/校|
|`advance_school_roster` / `advance_rosters`|隣接年度・同career seed・同学校を要求。学年だけ進級し、卒業枠に新入生を生成。前者をarchiveから直接再利用。後者の学校単位streaming方針も維持|
|`CareerRosterArchive.advance_and_save`|前年度の保存正本から算出し、校年ロスターと学年以外の恒久identityを1 SQLite transactionで追記。今回の2027保存を担当|
|`DemoStore` / `DemoReader`|Stage110のnamespace/demo実体ID、所有lease、Windows native pin、link/reparse/hardlink拒否、sidecar/hot journal拒否とRO全件監査をそのまま使う|
|`verify_prefix` / event・bracket oracle|全31保存結果をseed全再実行、完全A照合、進出台帳/最終順位を独立検証。完了の根拠として再利用|
|`yamanashi_tournament_registration`|2026の32team/33schoolと640登録を固定。2027大会用に流用しない|
|`CareerCompetitionOutcomes`|製品のsealed年度＋MAIN実試合に基づく学校順位/資格契約。今回は合同teamを含む別の登録形式なので変換・注入しない|
|`career_player_records`|製品の旧school-keyed完全Aとarchiveを結ぶ。今回はteam ID＋origin_school_idの登録完全Aなので既存DemoReaderの参照・`player_totals`を使い、製品へ変換しない|
|`career_history_browse_model`|製品の封印年度、過去年の所属・索引検索・読取境界を持つ。2027は大会未実施なのでsealed製品年度として登録せず、独立RO viewを提供|

## 2026完了の真正な受入条件

`SelfCreated2026`は空のlive `TemporaryDirectory`を所有する呼出元だけが作成できる。
従来の`DemoNamespace.create` / `DemoStore.create`で自己生成し、既存31試合writerで架空大会を完了させる。
再開は親が一時領域を保持している間のprivate capabilityのみ。実ユーザーのデモ/saveを選択する機能はない。

`verified()`は既存`DemoReader.snapshot()`による次の全検査を毎request行う。

1. namespace/demo marker、recipe seed、実体ID、schemaの完全一致。DELETE journal、整合性、FK、未知ファイルも検査する。
2. 保存完全AのSHA・schema・元学校/永久ID・全計算seed再実行・独立event oracleを照合する。
3. 独立bracket oracleの31進出台帳、32team最終順位と、全SQL行を照合する。
4. 31試合完了かつ最終32team順位を要求。GUIの31/31や手書きcomplete flagは使わない。
5. **検証後にSQL `school_rosters`の保存JSONを実際にdecode**し、33校・各20人・660 distinct IDs、SHA・canonical JSON・2026正本との一致を確認する。生成器から返った2026オブジェクトをそのまま次年度の入力にしない。
6. DB、demo marker、namespace markerのSHAを読取前後で比較。出典契約には正確なnamespace/demo実体・metadata、DB bytes SHA、31結果checkpoint、学校正本集合SHAを保存する。

0/1/16/30件、欠損・重複JSON・破損・異seed・別ゲーム・marker/schema/実体不一致を拒否し、ターゲットを作成しない。SHAとmarkerは整合性証拠であり認証済み出典とは主張しない。

## 別領域の2027正本と全33校の年度受理

2026と別の空の自己所有`TemporaryDirectory`に`annual_rosters.sqlite3`を排他的に新規作成する。
元2026の`demo.sqlite3`へ年次追記せず、markerや履歴も変更しない。
最初に検証済み保存2026学校ロスターを`CareerRosterArchive.save_initial_roster`で新領域に保持する。
以後`advance_and_save(next_year=2027, career_seed=430103)`を学校ID順に適用する。
2027 seedの`generate_school`による20人再生成は禁止。career seedは元学校保存正本と同じ値である。

学校ごとの追記では、2026の3年生8人が卒業し、1年生5人・2年生7人が2・3年に進級し、新入生8人を補充する。
33校の計数は卒業264・進級396・新入264・2027現役660。進級選手は学年以外の全Playerフィールドを比較し、元roster_noも保持する。
新入生IDは既存ロジックに従う。全校間・2026全永久IDとの衝突を検査し、氏名一致による同一人物扱いはしない。

学校別append成功と年度全体の受理を分離する。
正常な学校ID順prefixだけは`incomplete_rosters`としてprivate capabilityで再開できる。
欠損校、異seed/正本、余計な年度、恒久identity変更、競合、不完全初期書込はfail closed。
33校分の保存ロスター・恒久identityを全件RO照合した後、924選手の卒業/進級/新入mapping（前後Player SHA）と集計・学校ロスター集合SHAを単一の確定transactionで保存する。
確定前は33校分の生成が済んでいても`accepted=false`で、2027の閲覧年度を公開しない。
確定前の故障はrollback、校別commit後の強制終了は同じIDから再開、確定直後のACK喪失はbytes不変の再試行となる。
dirty/hot journal、途中のmappingだけ、偽確定行は修復せず拒否する。

新DBの全テーブルにはUPDATE/DELETE拒否triggerを設ける。
root/DB/leaseの実体ID、全親のlink/junction/reparse、hardlink、未知項目、DELETEヘッダを接続前に検査し、Windows native pinとOS leaseで競合・差替えを防ぐ。
各SQLite接続はcommit/rollback後にnative close。ROはmode=roとquery_onlyを用い、immutableでlockを無視しない。
原子性は**校別archive追記と全33校確定のそれぞれ1 SQLite transaction**。2026と2027の複数DB原子性、媒体障害の完全復旧は保証しない。

## 学校・選手の年度横断読取

`lab.browse()`は2026の全件完了検証と2027の全件RO検証を再度行い、request内だけのdetached viewを返す。永続cacheではない。

|読取API|2026|2027|
|---|---|---|
|`view.school(sid, year=...)`|保存旧20人、参加team/元学校、試合、team順位。合同参加注記あり|継承後20人、試合・team・順位は空。大会未予定/未実施|
|`view.player(pid, year=...)`|プロフィール、元学校、入学年、試合別投打/通算。新入生は未入学・profileなし|進級/新入はactive、卒業生はgraduated。試合別成績なし・通算空、過去情報は2026指定で引き続き参照|

2026農林・塩山の合同team履歴はteam IDのまま保持する。
両校の2027学校ロスターは別々に作り、合同の勝敗・優勝を単独学校成績へ複写しない（`school_standalone_outcomes=None`）。
660学校台帳と640大会登録を区別し、未登録20人も個人履歴検索から落とさない。
2027の合同継続、出場資格、登録枠、シード、日程は作成しない。2027大会の実行APIもない。
本StageはRO APIと自己生成例に限定し、年次Tk小画面は追加しない。既存Windows native mapped Tkは従来CIで全回帰する。

## 長期運用への調査

coreの進級関数・archiveに人為的max_yearはない。現役20人/校、3学年を維持し、卒業選手identityと校年snapshotはappend-only。
`CareerRosterArchive.player_history`は永久identity索引から元学校/入学年を確認し、(school_id, year)索引で最大3校年だけを読む。全年度decodeが必須ではない。
隔離した1校の**ロスターだけ**を2026〜2226（201 snapshot、200回進級）追記し、各年のID連続性・卒業・再利用なしと最古選手の履歴保持を検証する。試合もゲーム年度の受理も作成しない。

Stage111の試験用`browse()`は固定2年度・33校/31試合を全検証するので、これを200年分の製品年度照会へ一般化しない。
今後の製品側は「active20人/校」「過去選手は索引検索」「旧大会Option Aはappend-only」を維持し、sealed年度単位の検証証跡と範囲照会を設計する必要がある。
今回の200年ロスター試験を2027大会完了や2028実ゲーム開始の証拠にはしない。

## CIと非対象

新Windows Python3.12 headless gateはskip0。既存Stage100〜110、実31試合save/restart、Windows native SQLite/Tk、全unittest、関東17校E2Eを維持する。
旧13版はStage94/99/100/101/102/103/104/105/106/107/108/109/110の真の各commit checkoutで生成した模擬候補をRO内容verifyし、catalog338/data106bytesとreplay許可境界を照合する。旧コードを新結果で偽装しない。
実ユーザーデータの互換性、個人PCの目視・サインアウト/再ログイン・PC再起動は未検証で、自動CI成功と区別する。
旧デモ/セーブ変更・移行・復元、履歴削除/GC、全国GUI接続、2027公式出場資格/合同継続/大会試合・日程、2027本番slot公開、EXE/installer・配布は対象外。
成果物は実測報告・手動手順とPR。最終headの全必須CI成功後も未マージ・auto-merge無効でレビュー待ちにする。
