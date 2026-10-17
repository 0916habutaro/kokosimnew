# Stage43G-117：2027架空8チーム大会7試合・汎用ブラケット・年度横断履歴

2026-10-17、Issue #289。着手条件（PR #288のmainマージ）はIssueコメントで確認済み。
起点はmain `df91f062e51619f65c66f0fb3f42b06e4f8de872`。
作成済み `stage43g117-2027-fictional-eight-team-bracket` を使用する。
学校は実master、選手・結果はゲーム内架空。Windows専用・個人利用・非配布。

## 棚卸し：Stage116までの固定箇所と今回の責務

|入力／既存実装|固定箇所・現状|Stage117での扱い|
|---|---|---|
|Stage116 `saved_fictional_tournament.py`|`_prepare` が学校組 `(196),(197),(202+220)` と `(3,4,1)` に一致しなければ拒否。`_input` は `len(results)>=2` で完了、`pair` は「試合1の2枠」→「勝者対BYE」を直書き。DDLは `sequence BETWEEN 1 AND 2`、`rank BETWEEN 1 AND 3`。受理は2試合目と同時|**一切編集しない**（v1契約・DB・テストを保持）。`decode_request`・`_team`（20登録→先発9・投手順）は読取専用で再利用|
|Stage116 `fictional_tournament_oracle.py`|`len(entries)!=3`、`len(slots)!=4`、`slots[1] is None`、試合数2、順位3件に固定|編集しない。新しい汎用進出oracleを別moduleで実装し、v1の3team結果に対する回帰照合だけに使う|
|Stage115 `competition_evidence_gates.py`|`DrawRules` は `single_elimination`・`n<=size<2n`・2の冪・`bye=size-n` を一般に検査。`Schedule` は `log2(size)` 個の昇順・異なる日付。`SeedRules` は `1<=n<=len//2`|編集しない。8team/8slot/bye0/3日付をそのまま通す。毎操作 `dry_run(lab, request)` を要求本体で再実行|
|Stage114 `saved_practice_match.saved_authority`|保存31試合とStage111受理を再検証し、2027保存SQL JSONを直接decode|毎操作の出典authority。閲覧用の期待transitionや再生成選手は試合入力にしない|
|Stage111 `SelfCreated2026`／`AnnualRosterLab`|保存2026全31試合→全33校受理、660現役／924永久ID|必須の出典。Stage113の100校roster-onlyやStage108の2026登録は2027資格へ昇格しない|
|`registered_match_driver._run`／`registered_full_a_oracle.event_oracle`|Stage105限定モデルの計算と、乱数・driver進塁を使わない独立再集計|7試合すべてを `_run` で新規計算し、`event_oracle` と同seed再計算で検証|
|製品 `brackets.run_single_elimination_ranking`|resolverで全試合を一括決定。BYEは末尾奇数、試合単位の保存・再開や前結果SHAの束縛なし|**編集しない・使わない**。段階保存に合わないため、純データの別ブラケットmoduleを新設|
|`CompetitionRun`／`CareerCompetitionOutcomes`／`HistoricalMatchArchive`|製品の正式結果アーカイブ|架空結果を書き込まない。参照もしない|
|既存2026山梨32team全31試合（Stage109–110）|保存正本。Stage111 fixtureが毎回生成|再利用のみ。今回のテストclassで1回だけ生成し、全caseで共有（原本検証は各操作で省略しない）|

新規ファイル：

- `phase2_engine/fictional_bracket.py`：汎用シングルエリミネーションの構造（純データ、DB・RNG生成・driverなし）。
- `phase2_engine/fictional_bracket_oracle.py`：独立進出oracle（上記moduleをimportしない、別アルゴリズム）。
- `phase2_engine/saved_fictional_bracket.py`：版 `stage43g117_fictional_bracket_v2` の追記専用SQLite store。
- `tests/test_stage43g117_bracket.py`・`tests/test_stage43g117_compatibility.py`・`tests/stage43g117_support.py`・`tests/stage43g117_audit.py`。

製品writer/schema/catalog/data、Stage111–116のコードと契約は変更しない。

## 架空8team（単独7＋合同1、9校）の要求

Stage115の型付き `CompetitionRequest` を試験側で明示的に組み立てる（`tests/stage43g117_support.py`）。
namespaceは `fictional:stage117-owned-eight`、team IDは `<namespace>:team1..team8`。

|entry|元学校|登録|
|---|---|---|
|team1〜team7（単独）|SCH000196, 197, 198, 199, 200, 201, 203|各校の保存2027ロスター20人|
|team8（明示合同）|SCH000202＋SCH000220|各校先頭10人、計20人|

- `EntrySet`・`JointComposition`（team8だけ）・全team `QualificationDecision(eligible=True, basis='explicit_scenario', exempt=False)`、
  `prior_year_receipt_sha256=None`。2026の参加実績や合同を2027資格・合同継続の根拠にしない。
- `DistrictRules(rule_version='fictional_yamanashi_v2', district_id='scenario-district')` で9 program全件を明示。
- `SeedRules`：team1をseed1、team2をseed2として宣言（架空の宣言であり公式シードではない）。
- `DrawRules('single_elimination', 8, 8, 0)`、`Schedule` は架空シナリオ日 `2027-07-10／07-12／07-14`。
- 全evidenceは `Authority.FICTIONAL_DECLARATION`、year 2027、source `self-created declaration/...`。
  実行層はStage116と同じく official／verified／URL／公式／認証を含むラベルを拒否する。

実行時に検査する条件：8teamの学校・program・永久選手IDが相異なる、単独は1校20人、合同は2校10+10、
各teamに登録投手がいる。卒業者・他校選手・重複参加・元学校書換・別source（別の物理fixture）・別年は拒否。
2027実在の出場資格・合同継続・日付は推測しない。公式・製品開始フラグは常にFalse/None。

## 汎用ブラケット（`fictional_bracket.py`）

`plan_bracket(entries, seeds, rng, size)` が配置を作り、`Bracket` が試合グラフを持つ。

- 対応：`2<=n<=size<2n`、sizeは2の冪で **4〜32**（今回の実行は8、回帰は3と4、純構造は2〜32を検査）。
- 配置：宣言シードを標準のシード位置（1→先頭、2→末尾、3・4→各半分の反対端…）に置き、
  残りはシナリオ専用RNG（`rng_for(scenario_seed, 'stage117:draw:'+namespace)`）でshuffleして空き枠へ。
  BYE（`None`）はシード上位の対戦相手枠から順に割り当てる。3team/size4では旧v1と同じく「seed1にBYE」。
- 試合グラフ：1回戦は隣接2枠、以降は前ラウンドの隣接2試合の勝者。片側がBYEの1回戦は試合を作らず、
  そのteamを「BYE進出」として次ラウンドへ送る（勝利数に数えない）。
  実試合だけに通し番号 `sequence` を振る（ラウンド順→ブラケット順）。8teamでは1回戦1–4、準決勝5–6、決勝7。
- 各試合の入力は「前の実勝者」だけから決まり、前結果全体のSHAを束縛する。
- 順位はシングルエリミネーションの標準：優勝1、準優勝2、準決勝敗退3（同順位）、準々決勝敗退5（同順位）。
  **全試合完了まで順位・優勝は作らない**（途中はNone／空）。

独立進出oracle（`fictional_bracket_oracle.py`）は上記moduleをimportせず、配置リストを
「隣接ペアを畳み込む」別アルゴリズムで再現し、得点から勝敗を導出して勝者申告だけを信用しない。
試合の順序・参加team・seed・match_id・日付・勝者・敗者の再出場禁止・順位を照合する。
3team/v1回帰では、Stage116の実2試合結果に対して汎用oracleと旧oracleが同じ対戦集合・BYE・優勝・順位になることを確認する
（旧v1の決勝は「試合1勝者が先攻」の固定順なので、先攻後攻順は比較しない）。

将来の5〜7・16・32teamは同じ配置関数とグラフで表せる。ただし32team/31試合の実保存は今回行わず、
時間は実測からの推定として報告書で区別する。

## 選手と計算

保存2027 SQL rosterの `Player` から永久ID・元学校・program・入学年・学年を維持し、
能力は `SchoolAwarePlayerAbilityGenerator` で2027／ability_seed430103として計算する（Stage116と同じ）。
先発9人・投手順はStage116の `_team` をそのまま呼ぶ（primary優先、不足位置だけ登録野手を明示配置、
先発に進級実出場者・新入生・全構成校を含む、交代投手は投手打順枠へ）。Stage116の挙動と完全に一致する。

試合入力 `BracketMatchInput`（版 `stage43g117_fictional_bracket_match_input_v2`）は、record_kind、年、namespace、
scope（`LAB117:2027:FICTIONAL:<namespace/seedのdigest>`）、match_id（`<scope>:r<round>:g<slot>`）、架空日、
sequence、round、scenario_seed、match_seed、ability_seed、契約SHA、前結果SHA、両team入力を持つ。
match_seedは `rng_for(scenario_seed, 'stage117:match:<sequence>')` で結果と独立に導出する。

7試合は `_run(match, match.match_seed)` で毎回新規計算する。固定得点や2026・2027練習・Stage116 2試合の
イベントを転記しない。得点・打席数・イニング数は実測値を正本とし、事前に決めない。
検証は `event_oracle`（得点・全イニング・打撃・投手・責任投手）と同seed再計算の全一致、
および独立進出oracle。試合不成立（30回／10000打席上限）・改ざん・異seed・誤勝者は保存しない（fail closed）。

Stage105限定モデルと製品MatchSimulator全体との差（Stage116から変更なし）：

|項目|Stage117で使う限定モデル|
|---|---|
|確率・投手交代|製品の確率／重み選択／交代判定とconfigを再利用|
|走塁|安打の塁打数分の固定進塁。確率的追加進塁なし|
|失策・野選|発生確率をfield_outへ合算。失策欄0|
|犠打・犠飛・盗塁・盗塁死|本driverでは発生せず成績0|
|投手責任|走者の責任投手を追跡。失策なしモデルの失点＝自責点|
|終了|9回以降の裏省略・サヨナラ。30回／10000イベント上限で不成立は保存しない|

## 版付き追記専用SQLite（`fictional_bracket_v2.sqlite3`）

自己所有 `TemporaryDirectory` 内の新DB。元2026・年次2027・練習・Stage116 v1とは別root／別DB。
STRICT表はすべてUPDATE／DELETE拒否trigger付き。

|表|内容|
|---|---|
|`bracket_contract`|要求・gate結果・出典receipt・配置・試合計画・全team入力のcanonical契約（1行）|
|`bracket_matches`|sequence・match_id・round・日・入力JSON/SHA・結果JSON/SHA|
|`bracket_advancement`|BYE進出（作成時）と実勝者進出（各試合）|
|`bracket_checkpoints`|試合ごとの出典receipt SHA・契約SHA・前結果SHA・保存後prefix SHA|
|`bracket_players`|実出場選手の永久ID索引（entry team・元学校・年・種別・namespace・match_id）|
|`bracket_ranks`|最終順位（決勝と同じtransactionでのみ作成）|
|`bracket_acceptance`|架空シナリオ内の最終受理（決勝と同じtransaction）|

1試合＝1 transaction（`BEGIN IMMEDIATE`、DELETE journal、synchronous FULL）。
全旧行を照合して差分だけINSERTする。結果・進出・出場索引・checkpointは同時にcommitされ、
決勝だけは順位・最終受理も同じtransactionに入る。

- ACK消失：同じ入力・同じ結果の再送はbytes不変で `False`。異結果・別入力は拒否。
- commit前例外はrollback。commit前の本物の強制終了で残ったhot journalは接続前に拒否し、自動回復しない。
- 保存スキップ（次でないsequence）・並べ替え・重複match_id・同seed別物理出典の入力混用を拒否する。
- 試合1・4・6・7のcommit直後に別processで `os._exit(73)`。次のprocessは全出典を再検証し、
  保存済みprefixの進出・未確定状態を読み、**前の本当の勝者だけから**残りを計算して完了まで再開する。
- root／DB／leaseの実体ID、単一hardlink、symlink／junction、未知sidecar、header、lease排他、
  SQLite lock、native handle close→rename→reopen、RO前後SHA不変をStage116と同じguardで検査する。
- 複数SQLite間の一括atomicity、本番復旧、電源断耐久性は主張しない。

再監査は毎回「全保存試合を `_run`＋`event_oracle` で再検証」する。1試合の再計算と独立oracleは
数ミリ秒で、7試合でもO(N²)の合計は1秒未満の見込み（報告書で実測）。支配的な費用は
各操作での出典再検証（保存31試合とStage111受理、2027 SQL decode）である。
`play_next` は「事前検証1回＋保存＋保存後の再監査1回」で、検証を省略せず呼出回数だけを整理する。

## 年度横断履歴・合同集計

`snapshot(practice_store=..., v1_store=...)` は次の4streamを year・record_kind・namespace・match_id で分離する。

|年|record_kind|対象|
|---|---|---|
|2026|fictional_tournament|保存山梨31試合（元competition scope）|
|2027|fictional_practice|保存練習1試合（LAB114:PRACTICE）|
|2027|fictional_tournament|Stage116旧3team試験2試合（`fictional:stage115-owned-demo`、LAB116）|
|2027|fictional_bracket_tournament|今回8team 7試合または保存済prefix（`fictional:stage117-owned-eight`、LAB117）|

練習・v1は同じ所有学校年から作られたstoreだけを受け付け、それぞれの独立RO監査を通す。

- `team(entry_team_id)`：entry単位の勝敗・試合・最終順位（未完了はNone）。BYEは勝利にしない。
- `school(school_id)`：stream別の試合と、今回scenarioのentry記録。`standalone_wins/losses` は単独entryだけ。
  合同構成2校は常に単独0勝0敗（Stage116 v1の合同勝敗も加算しない）。
- `player(player_id)`：永久IDで年度・種別ごとの状態（在籍／未入学／卒業）・profile・出場、
  今回scenario内の打撃・投手累計。合同選手はentry teamと元学校を両方返し、学校を合同IDへ付け替えない。
- 公式2027参加・資格・合同継続・日程・順位はNone、`official_year_verified`・`product_season_start_authorized` はFalse。

## 検証・CI運用

`python tests/stage43g117_audit.py --require-windows --json-output <新規report.json>`。専用caseはskip0必須。
不変出典（保存31→受理33→練習1→v1 3team 2試合）をclass内で1回だけ作り、各caseのtargetは独立。
毎case後に元4DBのSHAを照合する。出典検証そのものは各操作で省略しない。
fixture時間、case別時間、7試合run時間、DB bytes、CPU時間、最大RSS、コードSHAの実行前後不変を記録する。

旧版：既存旧18版に、真のStage116 main（`df91f06`）から自己生成したRO候補を加えて19版。
catalog338・master106CSV・候補bytes不変、restore／replay非許可を検査する。
全unittest、関東8都県17校E2E、既存Windows native Tk／SQLite・保存・年度履歴は維持する。
必須テストは減らさない。追加時間は実測で説明し、必要なtimeout変更は根拠付きで行う。

対象外：製品統合、公式2027情報の推定、32team実保存、50/100/200年の全試合実証、migration／restore／GC、
GUI改修、EXE／installer。hosted Windows CIと個人PCの目視／サインアウト・再ログイン／OS再起動は区別する。
最終headの全必須CI成功後も新PRは未マージ・auto-merge無効・レビュー待ちで停止する。
