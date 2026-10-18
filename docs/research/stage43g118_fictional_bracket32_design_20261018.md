# Stage43G-118：2027架空32チーム31試合の段階保存・再開・完全A・履歴とCI負荷監査

2026-10-18、Issue #291。起点はPR #290マージ後のmain `2cec50ca7818201f702a2512bfdd007a010b5dc8`
（親 `df91f06`・`77a5a1a`）。指定済みブランチ `claude/stage-43g-118-save-resume-v9mcpu` を使用する。
学校は実master、選手・結果はゲーム内架空。2027公式大会の参加資格・合同継続・日程・シード・組合せ・順位は
未確定のまま扱い、`official_year_verified=False`・`product_season_start_authorized=False` を変えない。

## 棚卸し：Stage117で何が32チームに対応済みか

|対象|Stage117時点|Stage118の判断|
|---|---|---|
|`fictional_bracket.py`|`MIN_SIZE, MAX_SIZE = 4, 32`。配置・試合graph・順位は2の冪4〜32で一般|**変更しない**。16／32をそのまま使う|
|`fictional_bracket_oracle.py`|配置リストの畳込みで任意ラウンド数を再現|**変更しない**|
|`saved_fictional_bracket.py`（v2）|DDLは `sequence BETWEEN 1 AND 31`、`round_no BETWEEN 1 AND 5`、`rank BETWEEN 1 AND 32`。`_prepare` の登録数検査は「単独20／合同10+10」で一般|**変更しない**。v2版のまま16／32を保存できるため、新schema（v3）は不要と判断|
|v2 `snapshot`|2026・練習・Stage116 v1・自scenarioの4stream|複数scenario（Stage117の8team・今回の16／32team）を並べる閲覧が無い → 新規 `fictional_scenario_history.py`（読取専用）|
|Stage116 v1・Stage115 gate・Stage111保存2027|—|編集しない。`git show 2cec50c:<file>` とbytes一致を試験で確認|

実測プローブ（補助Linux）で、v2 storeが32team・31試合を無変更で完走することを先に確かめた。
v2のscopeは版の規約どおり `LAB117:2027:FICTIONAL:<namespace/seedのdigest>`、乱数ラベルも `stage117:` 系のままである。
今回のscenarioは別namespace・別seedで区別する（scopeの接頭辞は版名であり、Stage117の試合を意味しない）。

新規ファイル：

- `phase2_engine/fictional_scenario_history.py`：複数のv2 storeを、それぞれ独立RO監査した上で年度・種別・namespace・match_idで並べる閲覧。
- `tests/stage43g118_support.py`：明示架空16／32team要求、計測付き子process transport。
- `tests/stage43g118_scale_cases.py`：実規模ケース（`unittest discover` の既定patternに入らない名前）。
- `tests/test_stage43g118_contract.py`：全unittestに入る高速検査（純graph、v2 DDLの上限、CI配線の存在）。
- `tests/test_stage43g118_compatibility.py`：真のStage117 main（`2cec50c`）から自己生成した20版目のRO候補。
- `tests/stage43g118_audit.py`：自己所有試験CLI（JSON報告、`--old-versions` で旧20版も実行）。
- `.github/workflows/stage118-fictional-bracket32.yml`：Linux／Windowsの専用並行job。

## 32エントリーの明示定義

出典は保存2026全31試合→Stage111で受理した保存2027の33学校・660現役・924累計永久IDだけ。
Stage115の型付き `CompetitionRequest` を試験側で組み立てる（Stage117の `scenario()` を再利用）。

- namespace `fictional:stage118-owned-thirty-two`、scenario seed 430118。team IDは `<namespace>:team1..team32`。
- 単独31：保存2027の学校ID順で、合同2校を除く31校（SCH000196〜201・203〜219・221〜228）。各校20人。
- 合同1（team32）：SCH000202＋SCH000220、各校の先頭10人。Stage116／117と同じ組だが、**2027の実際の合同継続を示さない**。
- 計33校・640人。全team `QualificationDecision(eligible=True, basis='explicit_scenario')`、`prior_year_receipt_sha256=None`。
- 宣言シード：team1〜4をseed1〜4（標準位置：先頭・末尾・各半分の端）。架空の宣言であり公式シードではない。
- `DrawRules('single_elimination', 32, 32, 0)`、`Schedule` は架空日 `2027-07-09／11／13／15／17` の5ラウンド。
- 抽選はv2の独立RNG `rng_for(430118, 'stage117:draw:'+namespace)`、各試合seedも結果と独立に導出。
- 全evidenceは `Authority.FICTIONAL_DECLARATION`、year 2027、`self-created declaration/...`。

毎操作でStage115 `dry_run` を要求本体で再実行し、`saved_authority` で保存SQLを直接decodeする（v2の挙動そのまま）。
卒業者・他校選手・合同11+9・entry ID重複・合同構成校の単独二重参加・合同宣言欠落・BYE数・64枠・4日付・2026年・
official namespace・「公式」ラベル・seed範囲外・別物理出典はすべて拒否する（`test_07`）。

段階実証の16team（`fictional:stage118-owned-sixteen`、seed 430218）は、単独15校（SCH000196〜201・203〜211）＋同じ合同1の17校・320人、
4ラウンド架空日 `2027-07-20／22／24／26`。

## 実際の31試合と完全A

1回戦16→2回戦8→準々決勝4→準決勝2→決勝1。各試合は保存2027 SQL rosterから `registered_match_driver._run` で新規計算する。
Stage117の7試合・2026の31試合・練習・v1の結果は転記しない。得点・イニング・投打・順位は実測値を正本とし、事前に決めない。

親processは保存済み31試合の全部について、`event_oracle`（得点・全イニング・打撃・投手・責任投手）と同seed再計算の一致、
前結果SHAの連鎖、独立進出oracleと汎用graphの順位一致、各ラウンドの参加teamが前ラウンド勝者だけであることを再検証する。
出場索引（`bracket_players`）はイベントの打者・投手とentry teamの集合に一致すること、各teamの実打者に進級者と新入生が含まれることも確認する。

## 試合単位SQLiteと強制終了・別process再開

保存はStage117 v2の仕組み（1試合1 transaction、append-only trigger、前結果SHA・出典checkpoint、永久ID索引、進出、
決勝と同transactionの順位・最終受理、ACK消失冪等、hot journal拒否、lease／identity guard）をそのまま使う。

**本番の試合計算は子processだけが行う**。親はstoreを閉じてcapabilityを渡し、子は全出典を再検証してから再開する。

- 32team：試合 **1／16／24／28／30／31** のcommit直後に `os._exit(73)`。次の子は0→1→16→24→28→30の保存prefixから、
  前の実勝者だけで次の試合を作る。最後に別の子が読取専用で31試合・順位・履歴5streamを確認する（PID 8個が相異なる）。
- 16team：試合 **1／8／12／14／15** で同様。
- 各境界のDB bytesを親が保存し、境界ごとに試合数＝checkpoint数、決勝前の順位・受理0件を確認する。

境界の選択：1（最初の保存）、16（1回戦完了＝ラウンド境界）、24（2回戦完了）、28（準々決勝完了）、30（準決勝完了）、31（決勝＝順位・受理と同transaction）。
すべてのラウンド境界を通るため、残りの中間試合を個別に強制終了する追加ケースは置かない（費用は子1回あたり出典再検証の数十秒）。

決勝境界の破壊試験（`test_05`）は、30試合時点の保存bytesを**新しく作った自己所有store**へ書き込んでから行う
（同一要求・同一seed・同一出典なので契約は同一、inodeも同一。書込み後に全30試合の再計算と独立oracleを含む全再監査を通す）。

- 決勝のcommit前rollback：bytes不変、順位0件。
- 決勝commit後のACK消失：同一再送は `False` でbytes不変、異seed結果は拒否、完了後の `play_next` は拒否。
- 決勝の本物のprecommit強制終了（子process）：hot journalが残り、接続前に拒否し、DBとjournalを変更しない。

31試合DBの改ざん（`test_06`、同じく新storeへ複写）：未知表、出場索引の追加・削除・entry付替え、Stage117の索引行の混入、
試合SHA、決勝行の削除（順位を残したまま）、checkpoint、順位の変更・削除、受理削除、進出の付替え、契約の日付変更を拒否し、RO監査でbytes不変。

複数SQLite間の一括atomicity・本番復旧・電源断耐久性は主張しない。

## 年度横断履歴・合同勝敗の分離

`scenario_history(stores, practice_store=, v1_store=)` は各v2 storeの `snapshot()`（出典再検証と全再監査）を呼んでから、
次の6streamを `(year, record_kind, namespace)` と全体で一意なmatch_idで分ける。

|年|record_kind|namespace|試合|
|---|---|---|---|
|2026|fictional_tournament|保存山梨（元competition scope）|31|
|2027|fictional_practice|LAB114:PRACTICE|1|
|2027|fictional_tournament|Stage116 `fictional:stage115-owned-demo`|2|
|2027|fictional_bracket_tournament|Stage118 `fictional:stage118-owned-thirty-two`|31|
|2027|fictional_bracket_tournament|Stage117 `fictional:stage117-owned-eight`|7|
|2027|fictional_bracket_tournament|Stage118 `fictional:stage118-owned-sixteen`|15|

- 同一出典receiptでない、同一storeの重複、namespace／scope／match_idの重複は拒否。
- `school()`：streamごとに、そのstreamのentryだけで試合を引く（他scenarioのentry IDを混ぜない）。
  scenarioごとに単独entryの勝敗と合同entryの記録を分け、`standalone_wins_all_scenarios` は単独entryだけを合計する。
  SCH000202・SCH000220は全scenarioで単独0勝0敗、合同entryの記録だけを持つ。
- `player()`：永久IDで6streamの在籍／未入学／卒業、profile、出場（entry team付き）、scenario別の投打累計。
- 公式2027の参加・資格・合同継続・日程・順位・結果はNone。正式 `HistoricalMatchArchive`／`CareerCompetitionOutcomes`、
  製品セーブ、masterへは何も書かない。

## 時間・容量の計測とCI設計

計測するもの（`measured`）：出典fixtureの段階別時間（2026全31試合／2027受理／練習／v1／Stage117 7試合／32team作成）、
各試合の `play_next` 時間・CPU・保存後DB bytes、各試合内の層別時間（`_prepare`・`dry_run`・`saved_authority`・全再監査 `_rows`・
再計算・event oracle・新規計算）、子processの再開時間・CPU・最大RSS、31試合の全再監査時間、
1／8／16／24／31試合での `_rows`（O(N²)部分）と入力連鎖の時間、表別行数・ページ数・契約bytes・JSON bytes、拒否ケース別時間。

CI設計（2026-10-18のmain実測：Windows年次job 約65分44秒／上限90分、Stage117 step約20分22秒、全unittest約77分10秒／上限120分）：

- 実規模ケースは既存の2jobのどちらにも直列追加しない。`stage118-fictional-bracket32.yml` の専用jobを
  ubuntu／windowsの2行列で**並行**に走らせる（追加check 2件）。timeoutはLinux 90分、Windows 120分（実測から根拠を報告書に記す）。
- 実規模ファイルは `test_` で始まらないため全unittestのdiscoverに入らない。全unittestには高速な契約テスト（4件）と
  真のStage117 RO候補（1件）だけが入り、契約テストが専用workflowの存在・両OS・旧版オプションを検査する。
- 専用jobは `--old-versions` で旧20版RO（Stage94/99/100〜117）を同じjob内で再実行する。
- 既存の検査・timeout・skip条件は変更しない（path filterに今回のファイルを追加するのみ）。

対象外：製品統合・GUI接続（Stage120候補）、50／100／200年の全試合実行と全歴史Aの索引監査（Stage119候補）、
公式2027情報の推定、migration／restore／GC、EXE／installer。個人Windows PCの目視・サインアウト／再ログイン・OS再起動は未検証として扱う。
新PRは全必須CI成功後も未マージ・auto-merge無効でレビュー待ちとする。
