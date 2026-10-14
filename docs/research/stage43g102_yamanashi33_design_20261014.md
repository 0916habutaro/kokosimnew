# Stage43G-102 実規模県大会の入力監査・限定保存・履歴画面設計

Issue #259、PR #258マージ後の最新main `e3fca8a`から専用ブランチ `stage43g102-yamanashi33` を作成。Windows専用・個人利用・非配布、完全Option Aの全件保持、永久player_id、進行年数に人為上限なしを維持する。

## 入力監査と採用判断

**実大会33校としての受け入れは不可。マスター全33校を維持したゲーム内検証用大会として採用する。** 2026-10-14に、日本高野連の[地方大会会期公表](https://www.jhbf.or.jp/topics/info/260610_1.html)、山梨県高野連が速報配信責任者である[大会概要](https://baseball.omyutech.com/CupHomePageTop.action?cupId=20260013610)・[出場校一覧](https://baseball.omyutech.com/CupHomePageTeams.action?cupId=20260013610)・[組合せページ](https://baseball.omyutech.com/CupHomePageTournament.action?cupId=20260013610)を照合した。概要は32チーム、出場校一覧には農林・塩山の合同チームがある。33加盟校を33独立チームにする実大会仕様ではない。加盟校の台帳、正式な合同チームIDや複数学校所属、欠場の有無を完全な資格証明として確定したものではない。

|監査対象|現行マスター／runtime|公式との関係・扱い|
|---|---|---|
|competitions CMP000041|2026山梨夏、summer_local_qualifier、single_elimination、verified_structure|verified_structureは実参加一覧・組合せの完全な証明ではない。既存値の書換えなし|
|competition_stages STG000041|MAINのみ、single_elimination|個別公式シード・ブラケット枠は取り込まない|
|annual_templates|summer_areaがAREA000031からSCH000196–228を構築。33校、大会seed118436847|縮小・別学校・公式合同チーム化をしない。ゲーム内33独立校の入力|
|学校／チーム|33校×20架空選手、660永久ID|公式32チームとの差を明示。実選手名・実結果を生成元にしない|
|season_calendar CAL000041|7/5–7/22、抽選6/24、14日付候補。official_schedule|公表会期と一致するが、全個別日付を公式検証した意味ではない|
|stage_calendar|対象大会固有のoverrideなし。既存全stage coverage行をplanに保持|既存MAINの日付割当を使用。新しい公式日付解釈を追加しない|
|prefectural_branch_usage|山梨春・秋のnot_used行あり、夏を認定する専用行なし|春資格を夏に転用しない。summer_areaの独立rootだけ|
|seed／組合せ|main_seed_school_ids・main_bracket_slotsは空。deterministic_standard|公式抽選・公式シードではない。既存エンジンのゲーム用生成|
|依存／資格|root、pre-MAINなし、上流edge／bootstrapなし|他大会・全国代表資格・免除を付与しない|
|年末readiness|対象1大会の32試合とMAIN完了、年末到達が必要|未完了ならseal／outcome拒否。翌年登録・翌年ゲーム開始を実施しない|

現行学校名と出場校表記には略称・異表記がある。学校ID対応の正史修正は行わず、次を監査上の比較として残す。

|マスターの学校ID|マスター名|公式一覧との比較|
|---|---|---|
|SCH000196|帝京第三|帝京三の略称。資格ID対応の新規認定なし|
|SCH000197–201|北杜、韮崎、韮崎工業、日本航空、甲府昭和|一覧に同名／略称候補|
|SCH000202|農林|山梨農林・塩山合同の一方。fixtureは独立校|
|SCH000203–204|白根、巨摩|一覧に同名候補|
|SCH000205|青洲|一覧の青洲と比較。名称訂正なし|
|SCH000206–218|身延、甲府南、甲府商業、甲府西、甲府城西、東海大甲府、駿台甲府、甲府工業、甲府第一、甲府東、山梨学院、笛吹、日川|一覧に同名／略称候補|
|SCH000219|山梨|一覧に同名候補|
|SCH000220|塩山|山梨農林・塩山合同の一方。fixtureは独立校|
|SCH000221–228|都留、上野原、日大明誠、都留興譲館、富士学苑、吉田、富士北稜、富士河口湖|一覧に同名／略称候補|

製品変更前に一回限りの実AbilityMatchResolver／TournamentEngine dry runを実施した。64枠63ノードのうち31 bye、実試合32、初期scheduled実試合1、6ラウンド、全33校のMAIN順位を確認。試合日・件数はエンジンから取得し、7/5:1、7/6:16、7/7:8、7/8:4、7/9:2、7/11:1だった。**公式日程の候補を消費する現行割当は7/11に終わる。実大会の32チーム・31試合や個別日程の再現はこのStageでは未達。** 日程圧縮・公式シード・合同チーム対応は別の監査と契約が必要なため、このStageで一般エンジンを変更しない。dry runの集計は `audits/phase2/stage43g102/input_dry_run_linux_20261014.json` に保存する。

## 限定保存契約

`Yamanashi33FixturePersistence` は別resolver契約 `yamanashi33_game_fixture_v1` の明示opt-in。2026・年seed2026101201・大会seed118436847・ロスターseed430102・CMP000041・固定33校・確認済plan fingerprintだけを認可する。data全ファイルと能力／試合config JSONの集合・bytesのaggregate版を固定し、保存前に読み込み済repoとgenerator設定も照合する。未知provider、独自name_provider、事後cache、学校／seed／方式／日付／外部データ版・永久ID・所属・入学年・学年変更は拒否する。

既存Stage100/101契約・無指定service・8校操作demoは維持する。Stage101のsnapshot validatorのラウンド上限を既定3のクラス定数にし、この別契約だけ32にする。初回play以前に全33校のimmutable正本を確定し、初回manual（試合0件）から660人を保存する。ロスターcacheを出典として採取せず、同じ正本で新規進行と別プロセスreplayを行う。

保存はpreflight→JSON checkpoint→学校別roster commit→match archive→年度readiness→manual checkpoint→年度ledger seal→outcome commit。複数JSON／SQLiteは非原子的で、writer atomicityは保証しない。JSON直後、学校1校目／33校目後、17試合archive commit後、seal前後、outcome commit後の応答前停止を注入する。同一checkpointの欠落commitだけを別プロセスで再試行する。異なる試合checkpoint、stale manual、既存ID・SQL索引列／payload・ledger・outcome衝突は上書き前に拒否する。任意破損修復・電源断保証・並行writerの一般回復は追加しない。

## 独立oracleと閲覧

raw SQL＋JSON＋SHAの検証では製品decoder／validatorを呼ばず、索引列・payload・digest、33 rosters／660 identities、永久ID生成recipe、所属・学年・入学年、全32試合の完全A・選手対応とチーム／投打／イニング整合、年度manifestとseal、32試合source manifestとoutcomeを照合する。試合の敗退roundから独立に生成seedで同round内の表示順も再計算し、全33校のゲーム内順位を照合する。この順序は公式順位や同round校の競技力順位ではない。全33校の学校戦績と全660人の個人累計を保存行から独立集計し、製品read-onlyモデルと比較する。

`Yamanashi33HistoryTkPilot` は封印済の同fixture契約・plan identityだけを受理する別の閲覧専用画面。新規ゲーム／slot選択／restore／翌年開始の操作は持たない。既存Tkの年度→学校30件＋残り3件→学校履歴→試合イニング／投打成績→永久ID選手履歴を再利用し、明示したゲーム内検証ラベルと大会32試合・33校順位の詳細windowを追加する。native mapped Tkで全33校選択・大会詳細・完全A・選手履歴を検証し、終了時close／DB rename／reopen／integrity_checkを必須にする。個人Windows PCの手操作・目視確認とは報告しない。

## 互換性・CI・非対象

catalog対象の編集前に真のStage101 mainを一時領域へgit archiveし、別プロセスで候補export／verify済み。Stage94/99/100/101の真の旧候補を変更後コードでread-only内容verifyする。固定338入力集合は維持、変わるcatalog対象はlive_game_service.pyのみ。新catalog版と旧Stage101 aggregate版を登録する。新readonly Tkモジュールはreplay依存ではなく338集合に追加しない。真正性の証明・旧候補からの現行replay／restore許可ではない。data全bytes、master106 CSV、残り337catalog入力を維持する。

Windows Python3.12専用headless14件・native Tk1件はzero skipsの必須gate。Linuxは補助。既存Stage94以降backup、Stage100/101、Windows SQLite、全Python unittest、関東17校E2Eを実行する。公開artifactには集計・経過秒・save bytesだけを記録し、秘密／既存save内容／絶対path／個別SHAを載せない。既存saveは件数だけ・未検証、試験入力利用0。

実大会32チーム化、春資格、一般の複数大会統合、全国GUI、地区／pre-MAIN／feeder／選抜／免除、2027以降の開始、本番restore/import/activation、既存slot上書き・migration・削除／GC、EXE・配布関連は非対象。全最終head CI成功後も未マージ・auto-merge無効でレビュー待ちにする。
