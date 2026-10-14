# Stage43G-101 同年度共通ロスター出典・2大会保存設計

Issue #257、PR #256マージ後main `bd83cec`から専用ブランチ。Windows専用・個人利用・非配布、完全Option A全件保管、永久選手ID、ゲーム年数無制限の方針を維持する。

## 調査と対象選定

|出典／経路|確認した契約|今回の最小拡張／拒否|
|---|---|---|
|LiveSeasonGraphPlan／TournamentEngine|年seedから大会固有seedを作る。MAIN runtimeは大会ごとに生成され、未来roundは遅延登録|既存の独立MAIN 2大会に限定。calendar／annual／実runtimeを再照合|
|AbilityMatchResolver|通常は固定team seed→season seed→match seedの順。固定しない直接呼出しでは別大会seedで別選手になり得る|初回runtime前に年度＋学校＋built-in初年度recipe＋固定roster seedで正本を確定。match seedと分離。cache採取を正本化しない|
|InitialCareerPersistence|2026・CMP000029・既知8校・160選手・7試合専用、engine／planをbind|既存契約は維持。共有契約は別resolver契約名で明示opt-in|
|CareerRosterArchive|主キー(year,school_id)、immutable payload。永久identityはplayer_idと所属・入学年。学年だけは年次変更対象|2大会の学校集合のunionを一度保存。同名によるID修復・所属変更は拒否|
|pre-MAIN→MAIN／feeder／qualification|各県別のgate、免除、順位、封印済出典が必要。完全な全国接続ではない|今回は接続しない。依存edge・bootstrap・資格未解決・pre-MAIN入力を拒否|
|CareerCompetitionOutcomes／HistoricalMatchArchive|MAIN結果の実確認＋全年度ledger封印後だけoutcome確定。複数大会でも年単位のledger|両大会の実MAIN全件を照合。片方未完了なら封印とoutcome保存を拒否|
|CareerYearOperation／年次advance|明示rulebook／前年roster／資格出典が必要。翌年登録と実試合開始は別|2027年・学年更新・選抜・翌年資格は契約外。初年度入力を流用しない|
|read-onlyモデル|学校戦績は(year,competition)集計、個人成績は永久IDでjoin|2大会双方の学校／個人履歴を独立SQLと照合。閲覧時bytes不変|

2026マスター・calendarの山梨春CMP000105（4/11–5/6、structural）と山梨夏CMP000041（7/5–7/22、summer_area）はいずれもroot、MAINだけ、pre-MAINなし、上流依存／external bootstrapなしで、既存single-elimination MAINを実行できる。両templateは同県33校で学校集合が一致する。ただし春マスターはstructure_pending_verificationであり、構造モデルの学校一覧を公式の資格証明と扱わない。夏はverified_structure／公式日程。全国／春秋の未確認資格は解決しない。

そのため**自己生成検証fixture**として各4校・3試合に縮小する。春はSCH000196–199、夏はSCH000196/197/200/201。共通2校、union6校120選手、全6実試合。小規模入力は実出場資格ではなく試験入力であり、実大会の正史・移行・既存saveへ適用しない。県外学校入力は既存エンジンが拒否することも確認し、そのgateを維持する。試験slot／resolver契約名にもfixtureを明記する。

新契約はこの固定fixtureだけを受理し、任意大会の許可集合拡大APIにはしない。年度2026・年seed2026101201、独立roster seed430101、built-in generator、完全一致plan fingerprintを固定。大会seedは既存plannerの値を維持する。学校不足／別seed／別plan／外部roster_provider／事後cache／学年・入学年・所属・ID変化はfail closed。両大会の実試合日は別日になることをruntimeで確認する。複数大会同日を新しく認可しない。stage calendarは既存の全stage coverage validatorのため全行をfingerprintに含めるが、runtime／保存対象はこの2大会だけ。

組込みgeneratorと同じクラスでも独自name_providerを差し込んだ入力は別recipeなので拒否する。prepare／各保存preflightでdefault name providerの同一性も確認する。Stage100の単大会recipe契約は変更しない。

## 保存順序と故障境界

初回manualも試合0件の全6校を保存。preflight→JSON checkpoint→各校roster commit→match archive transaction→年度readiness→manual checkpoint→ledger seal→各大会outcome commit。JSON・roster・match・outcome・slot metadataは複数commitで**非原子的**。新journal／schema migrationは追加しない。

自己生成fixtureでJSON commit直後、ロスター1校目／最後のcommit後、片方大会の試合記録commit後、seal直前／直後、片方outcome commit後／両方commit後の応答前停止を注入する。同一入力・checkpointを別プロセスでreplayして欠けたcommitだけ再試行できることを確認する。既存履歴と衝突／古いcheckpoint／変造identity／結果不一致は書換えず拒否。checkpoint以前の未保存試合、任意のファイル破損、並行writerの一般的な回復は保証しない。

「ゲーム進行・load修復時も原本bytes不変」とは要求しない。read-only閲覧／候補verifyは前後全bytes不変、同一checkpoint再保存はimmutable DB bytes不変、進行後は既存row不変を区別する。

## 互換性・Windows・GUI

catalog対象ソースの編集**前**に真のStage100 mainを一時checkoutへexportし、そのコードの別Pythonプロセスで旧候補を生成・verify済み。Stage94／99／100のknown digestを内容verify用に保持する。338入力集合とmaster106 CSV集合／bytesを監査。変更入力はlive_game_service.pyだけを予定し、残り337入力不変を確認する。旧候補内容verifyは真正性の証明でも現行replay承認でもない。restore／import／activation・既存save移行は実装しない。

Windows Python3.12専用CIで実native connectionと例外frameを保持したまま製品closeをassertし、DB rename・再読取・integrity_checkをgate。2大会read-onlyモデルのnative mapped Tk履歴を最小確認する。Stage98/100の8校デモ画面を維持し、複数大会の操作画面・学校フィルタ等は次工程の日本語仕様に留める。Linuxは補助回帰。全Python3.12 unittest、関東17校E2E、Stage94–100関連CI、全PRチェック成功後も未マージ・auto-merge無効でレビュー待ち。

次工程UIは大会名と「自己生成検証」の区別、年度共通学校選択、同じ永久選手IDで2大会個人成績を比較する表示、未完了大会／年末封印blockerの表示を要する。正式GUI採用・全国scope・翌年進行は別Stageで出典を確認して判断する。
