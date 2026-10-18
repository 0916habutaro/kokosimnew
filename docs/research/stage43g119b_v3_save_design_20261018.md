# Stage43G-119-B：架空大会保存v3の差分検証・trusted checkpoint・旧版互換の設計

2026-10-18、[Issue #295](https://github.com/0916habutaro/kokosimnew/issues/295)。
起点はStage119-A（PR #294）マージ後のmain `86dee10e90b9224fa53ed43110945a11a6af5546`。
作業ブランチは `stage43g119b-v3-design`。**本Stageは調査と設計だけを行い、コード・テスト・workflow・保存DBを一切変更しない。**
v3の実装・故障系試験・実規模対照計測はStage119-Cで、本設計のレビュー完了後に別工程として行う。

学校は実master、選手・結果はゲーム内架空のままとする。2027公式大会の参加資格・合同継続・日程・シード・組合せ・順位は未確定として扱い、
`official_year_verified=False`・`product_season_start_authorized=False` を変えない。製品正式版の完成は宣言しない。

## 0. 証拠の区分

本書の記述は、次の区分を明示して書く。数値に区分がないものは置かない。

|区分|意味|本書での例|
|---|---|---|
|**[ソース]**|main `86dee10` のソース読解による事実・推論。実行していない|v2の呼出回数・計算量、rollback検出の欠落|
|**[既存実測]**|過去Stageの報告書・JSONに記録済みの実測。本Stageで再実行していない|Stage118報告の274.0秒・`_rows` 1.789秒など|
|**[補助計測]**|本Stageの補助Linuxコンテナ（Python 3.13.16／SQLite 3.45.1／4コア）での小さな確認。v2・v3の保存処理は実行していない|ストリーミングSHAの一致、5.59MBファイルSHAの所要|
|**[設計]**|v3の提案。未実装・未計測|状態遷移、schema案、失効条件|
|**[119-C]**|Stage119-Cで初めて得る実測・試験結果。本書では値を書かない|v2/v3対照の秒数・容量|

GitHub CI実測と個人Windows PCでの手動検証は、本Stageでは**どちらも行っていない**。

## 1. 既存v2（`phase2_engine/saved_fictional_bracket.py`）の分析

### 1.1 1試合保存（`play_next`）の呼出構造 [ソース]

|段階|行|内容|1試合あたり|
|---|---|---|---|
|`_prepare`|277・102|`_guard` の後、Stage115 `dry_run`（全gate）と `saved_authority`（保存2026全31試合・2027受理の再検証とSQL decode）を要求本体で再実行し、1 MB超の契約JSONを再構築|**2回**（事前＋commit後の `snapshot`）|
|`_audit`|281|schema/integrity/FK/journal_mode/契約一致、全試合decode、`_rows` による全表再導出と比較、前後のDBファイルSHA|**2回**（事前＋commit後）|
|`_rows`|158|保存済み全試合について `_input` 再構築・`_validate`（`event_oracle`＋同seed再計算）・前結果SHA・出場索引・進出・順位を導出|**4回**（事前監査N・旧行N・新行N+1・事後監査N+1）|
|新規計算|383|`_run(match, match.match_seed)`|1回|
|`_append`|338|`BEGIN IMMEDIATE` 下で全表を読み、旧行と完全一致を確認してから差分行をINSERT|1回|

`append()` 経由（外部から結果を渡す場合）も、事前の `_prepare`＋`_audit` と `_append` 内の処理で同じ構成になる。

### 1.2 計算量の精査 [ソース]＋[既存実測]

Issueは累積コストを「`O(N²)`相当」と書いているが、ソースを読むと次の2種類が混ざっている。

1. **再計算部分**：`_rows` 1回は保存済みN試合をそれぞれ `_run`＋`event_oracle` で再計算する（O(N)）。1試合で4回呼ぶので、大会全体ではO(N²)回の試合再計算になる。
2. **直列化・SHA部分**：`_rows` のループ内で `_input(prepared, results[:i])` が `_sha([r.to_dict() for r in results[:i]])` を計算し（166〜167・152行）、
   checkpoint行も `_sha([r.to_dict() for r in results[:i + 1]])` を計算する（175行）。これは `_rows` **1回の中で既にO(N²)** の直列化であり、大会全体ではO(N³)になる。

Stage118の実測（[報告](stage43g118_fictional_bracket32_report_20261018.md)）の「入力連鎖」は保存済み16→31試合で0.170→0.693秒（4.08倍）で、
(31/16)²≈3.75と整合する。`_rows` 全体は0.596→1.789秒（3.0倍）で、線形の再計算と二乗の直列化の和として説明できる。
31試合では係数が小さいため目立たないが、試合数を増やすと直列化部分が先に支配的になる見込みである（[ソース]からの推論、未計測）。

### 1.3 実際の最大費用は定数部分 [既存実測]

Stage118の32team／31試合では、`play_next` 合計274.0秒のうち `_prepare` が190.4秒（約69%、1回約3.3秒×1試合2回）、
`_rows` が79.0秒（約29%）、新規計算は0.1秒だった。**31試合規模では、O(N²)の部分よりも、毎回の出典再検証（定数×呼出回数）の方が大きい。**
したがってv3は「保存済み試合の再導出を差分化する」だけでは不十分で、出典再検証を信頼境界内で省略できる設計が要る。
ただし出典検証を弱めること自体が目的ではないので、省略してよい条件（§3・§4）を先に定める。

### 1.4 その他の超線形・定数費用 [ソース]

- `_append` の `additions = [r for r in rows if r not in old[table]]`（365行）はlistの所属判定で、出場索引（31試合で695行）に対しO(R²)。
- `_audit` の前後SHA（285・307行）はDBファイル全体をハッシュする（O(DBサイズ)、2回×2）。[補助計測] 5.59MBのSHA-256は本コンテナで1回約15ミリ秒。
- `BEGIN IMMEDIATE` 下で全表を `SELECT *` して比較する（361〜363行）。31試合では小さいが、表サイズに比例する。
- 契約JSON（1,022,247 B）を毎回再構築して文字列比較する。

### 1.5 v2で守られている性質（v3でも後退させない）[ソース]

- 1試合1 transaction、`BEGIN IMMEDIATE`、`synchronous=FULL`、DELETE journal以外の拒否（ヘッダbyte 18〜19）。
- 全表のUPDATE/DELETEを拒否するappend-only trigger。
- 根・DB・leaseの `(st_dev, st_ino)` 固定、リンク・junction・hardlink拒否、未知のsidecar（hot journal・WAL・SHM）を接続前に拒否し自動復旧しない。
- `fcntl.flock`／`msvcrt.locking` によるlease（process終了で解放）、WindowsではDELETE共有を拒否するhandle pin。
- 同一試合の同一結果の再送は `False`（冪等）、異なる結果・飛ばし・入力不一致は拒否。
- 毎操作で出典・要求・seed・契約を再検証し、全試合を独立oracle（`progression`）と汎用graph（`Bracket`）の2系統で照合。

### 1.6 v2の弱点・設計上の欠落 [ソース]（119-Cで再現試験により確認する）

|#|内容|影響|
|---|---|---|
|W1|保存内容は（出典bytes・要求・seed・コード）の決定的関数なので、全再監査を通るDBは「正しい結果列の先頭prefix」に限られる。**しかし短いprefixは常に正当**であり、同じinodeへ古い保存bytesを書き戻すrollbackは、identity照合も全再監査も通る。capabilityに保存試合数の下限がない|ACK済みの試合が黙って消える（内容の捏造ではないが進捗の喪失）|
|W2|`bracket_checkpoints` の行はすべて再導出可能な値で、外部の書き手が再計算すれば一致させられる。真正性の証拠ではなく整合性の記録にすぎない|checkpoint行を信頼の根拠にしてはならない|
|W3|leaseは協調的ロックで、APIを使わない同一権限の書き手（生のファイル書込み）は止められない。Linuxにはhandle pinもない|v2は毎操作の全再監査で検出している。v3で監査を省くなら別の検出手段が必須|
|W4|commit後の `snapshot()` が例外になると、DBには試合が入っているのに呼出側には失敗が返る|v2では冪等再送で吸収できる。v3でも「commit済みだがtrustは失効」状態を明示する|
|W5|commit直前の強制終了でhot journalが残ると、以後は常に拒否される（自動復旧禁止の方針どおり）|安全側だが復旧手段がない。v3でも自動復旧はしない（§7）|
|W6|DDLが `sequence BETWEEN 1 AND 31`・`round_no BETWEEN 1 AND 5`・`rank BETWEEN 1 AND 32` に固定|32team超へは新schemaが要る（119-Cでは32team上限のまま、§5.3）|
|W7|`fictional_scenario_history.scenario_history` は `type(s) is v2.FictionalBracketStore` を要求する|v3 storeの履歴閲覧は別の読取関数が要る（v2側は変更しない）|

## 2. v3の目標と非目標 [設計]

目標：

1. v1/v2のコード・schema・保存DB・出力・契約・テストを一切変更しない。v3は別version・別schema・別ファイル名で新設する。
2. 同一process・同一storeでの連続appendを「差分検証」で行い、保存済み全試合の再計算と出典の全再検証を毎回は行わない。
3. 再開・不明な変更・例外・完了受理の前など、信頼が切れる/重要な境界では、v2と同等の「全件再監査（`full_audit`）」を強制する。
4. 差分検証で書いた表と、`full_audit` の独立導出結果が全表で一致することを試験で常に確認する。
5. v2の弱点W1（rollback）に、呼出側が保持する外部anchorで対処する。

非目標：同一権限の攻撃者に対する暗号学的な真正性証明、複数SQLite間の一括atomicity、電源断耐久性の主張、
hot journalの自動復旧、WAL採用、32team超のbracket、50/100/200年の実測、製品セーブ・GUI統合、公式2027情報の推定。

## 3. 信頼モデルと信頼境界 [設計]

### 3.1 前提となる性質

- **決定性**：v3でも試合結果・全派生表は（出典bytes・要求・scenario seed・実行コード）の決定的関数とする。DBに非決定的な情報（時刻・PID・監査ログ）を書かない。
  これにより `full_audit` は「全表を最初から再導出して比較する」だけで完結し、通ったDBは正しい結果列のprefixに限られる。
- **checkpoint行は信頼の根拠にしない**（W2）。DB内のSHA・chainは整合性の検査値であり、外部の書き手が再計算できる。
- **信頼の根拠は2つだけ**：(a) `full_audit` による再導出、(b) 同一process内メモリに保持した、自分が検証・commitした直後のファイルbytesのSHA-256（trusted digest）。

### 3.2 アクターと保証範囲

|アクター|例|v3の扱い|
|---|---|---|
|同一storeオブジェクト|同じprocessの連続append|trusted fast pathの対象|
|同一process内の別オブジェクト・別thread|同じDBへ2つ目のstore|leaseで拒否（v2同様）。storeは `RLock` で直列化|
|別process（API利用）|二重起動|lease取得失敗で拒否|
|同一権限の生の書き手|ファイルを直接書き換えるツール|**防げない**。次の操作のdigest照合で検出し、trust失効→`full_audit` 強制|
|offline改変・ファイル交換|session間のDB差替え・同inodeへの上書き|再開時は必ず `full_audit`。交換はidentityで、同inodeの古いbytesはanchorで検出（§3.4）|
|SHAを再計算できる攻撃者|checkpoint捏造|fast pathではdigest不一致、full auditでは再計算不一致で拒否|
|process memoryを書き換えられる攻撃者|デバッガ|**対象外**（同一process内メモリは信頼境界の内側と定義する）|

### 3.3 trusted digestを取る時点

commit後、**読取transaction（SHARED lock）を保持したまま**DBファイルbytesをハッシュし、新しい行だけを主キーで読み戻して期待行と比較する。
SHARED lock中はSQLiteの書き手はcommitできない。生の書き手がcommit直後から読取開始までの短い隙に整合的な改変を入れる余地は残る（残余リスク）。
この残余が正しくない内容を「完了受理」まで運ばないよう、**決勝（順位・受理を書く試合）のcommit前と再開時には必ず `full_audit` を行う**（§4.3）。

出典（保存2026・2027受理・練習・v1など、`lab`/`lab.source` 配下のファイル）についても、`full_audit` 成功時に各ファイルの `(st_dev, st_ino)`・サイズ・SHA-256を
trusted source digestとして記録し、fast pathではこのbytes照合だけを行う。出典検証は（bytes・コード）の決定的関数なので、bytesが同一なら再検証結果も同一である。
照合対象のファイル一覧は `annual._sha`・`_evidence()`・`saved_authority` が実際に読むファイルから119-Cで確定し、一覧外のファイルを読む経路が無いことを試験で確認する。

### 3.4 rollback対策の外部anchor（W1）

`append` は `AppendReceipt(sequence, chain_head, db_sha256)` を返す。呼出側は最新のreceiptを保持し、`resume(capability, lab, anchor=receipt)` に渡す。
`resume` は `full_audit` の後、保存試合数がanchorの `sequence` 以上であり、その位置の `chain_head` がanchorと一致することを要求する。
anchorより短いDB（古いbytesへのすり替え）は拒否し、自動で進め直さない。**anchorを持たない／anchor自体が古い場合はrollbackを検出できない**ことを仕様として明記する。

## 4. 状態遷移とtrusted checkpointの失効 [設計]

### 4.1 状態

|状態|意味|許可される操作|
|---|---|---|
|`TRUSTED`|直近の `full_audit` またはfast path appendの後で、trusted digest・trusted source digest・メモリ上の検証済み結果列・chain headを保持|`append`・`play_next`・`next_input`・`snapshot`（fast）・`full_audit`・`close`|
|`REVOKED`|trustを失効した。DBは正しい可能性もあるが、未検証とみなす|`full_audit`・`close` のみ。他は拒否（暗黙のfull auditもしない）|
|`COMPLETE`|決勝と受理が `full_audit` 付きでcommit済み|`snapshot`・`full_audit`・`close`。appendは冪等再送のみ|
|`CLOSED`|handle・lease・pinを解放済み|なし|

`create`／`resume` は内部で `full_audit` を行い、成功時だけ `TRUSTED`（完了済みなら `COMPLETE`）を返す。失敗は例外で、storeは得られない。

### 4.2 失効条件（`TRUSTED`→`REVOKED`）

1. 任意の公開操作の途中で例外が出た（入力拒否の `ValueError` を含む。commit前後の `fault` 注入も同じ）。
   ※入力検査で拒否しただけの場合も失効させる。理由は、拒否経路でもDBを読んでおり、判断を単純化して「例外後は必ず再監査」とするため。費用は119-Cで測る。
2. DBファイルのSHA-256がtrusted digestと異なる、またはサイズ・identityが異なる。
3. 根ディレクトリに `DATABASE`・`LEASE` 以外の名前が現れた（hot journal・WAL・SHMを含む）。
4. 出典ファイルのidentity・サイズ・SHA-256のいずれかがtrusted source digestと異なる。
5. `os.getpid()` が `full_audit` 時と異なる（fork後のtrust持越しを禁止）。
6. SQLiteヘッダの `application_id`・`user_version`・journal形式が違う。
7. 前回 `full_audit` からのfast path append数が上限 `K` に達した（多重防御。暫定 `K=8`、119-Cの計測で決め、契約に固定値として書く）。
8. 明示的な `invalidate()` 呼出。

`REVOKED` から戻る方法は `full_audit()` の成功だけとし、失敗したstoreは `close` するまで `REVOKED` のまま全操作を拒否する。
時刻（経過秒数）による失効は、結果を非決定的にしないため採用しない。

### 4.3 `full_audit` を強制する境界

- `create`・`resume`（process再開・OS再起動・権限再確立・ファイル交換の可能性はすべてここに含まれる）。
- `REVOKED` からの復帰。
- **決勝（受理・順位を書く試合）のcommit直前**：BEGIN IMMEDIATEを取る前に `full_audit` を通し、そのtrusted digestと書込み直前のdigestが一致することを確認する。
- 完了後（`COMPLETE` 遷移時）にもう一度。
- 上限 `K` 到達時。

### 4.4 fast path append（擬似コード）

```text
with mutex:
  require state == TRUSTED
  guard()                      # 名前一覧・identity・リンク・ヘッダ（v2の_guard相当）
  check_source_digests()       # bytes照合のみ（再検証しない）
  expected = build_input(trusted_results)   # chain headから O(1)、前の実勝者はメモリの検証済み列から
  require identical(match, expected); validate(result, match)   # 新しい1試合だけ再計算＋event_oracle
  if sequence <= len(trusted_results): 冪等判定して return False（DBに触れない）
  rows = incremental_rows(trusted_state, result)                # §6
  if this is the final: full_audit() を先に実行（§4.3）
  BEGIN IMMEDIATE
    require sha256(db file) == trusted_digest                    # 書込みlock下で再確認
    require SELECT count(*) / max(sequence) == len(trusted_results)
    INSERT rows
  COMMIT
  BEGIN (read)                 # SHARED lock
    new_digest = sha256(db file); 新しい行を主キーで読み戻して rows と比較
  END
  trusted_digest, trusted_results, chain_head = new_digest, +result, new_head
  return AppendReceipt(...)
例外時: state = REVOKED; 再送出
```

v2との違い：保存済み試合の再計算・出典の全再検証・全表の比較をしない。代わりにbytes照合（O(DBサイズ)、[補助計測] 5.59MBで約15ミリ秒/回）と、
新しい1試合だけの検証、`progression`（再計算を含まない純関数、O(N)）による進出・順位の導出を行う。
**この見込みは未計測であり、v3がv2より速いという数値は119-Cの実測まで主張しない。**

## 5. データモデル（schema案）[設計]

### 5.1 識別

- `VERSION = 'stage43g119_fictional_bracket_v3'`、`INPUT_VERSION = 'stage43g119_fictional_bracket_match_input_v3'`。
- ファイル名 `fictional_bracket_v3.sqlite3`・`fictional_bracket_v3.lease`。v2の `_guard` は名前集合 `{v2 DB, v2 lease}` の完全一致を要求するので、v3の根ディレクトリはv2では開けない。
  v3側も名前集合 `{v3 DB, v3 lease}` の完全一致を要求し、v2/v1のファイルが同居する根を拒否する。
- `PRAGMA application_id` に固定の32bit値、`PRAGMA user_version=3` を作成時に書く。`_guard` でヘッダbyte 68〜71・60〜63を接続前に読み、v2 DB（両方0）を誤採用しない。
- 計画の導出（slots・games・match seed・scope）は、乱数ラベルとscope接頭辞をv3固有にする（例 `stage119:draw:`・`LAB119:2027:FICTIONAL:`）。
  v2と同じ要求・seedでも別scenarioとして区別され、`match_id` が衝突しない。v2との対照比較（§8）は「同じ（teams・match seed）を与えた試合内容の一致」で行う（§8.2）。

### 5.2 表（DDLのラフ案）

```sql
CREATE TABLE v3_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  payload TEXT NOT NULL,            -- 正規化JSON。games数・source_receipt・計画・teamsを含む
  payload_sha256 TEXT NOT NULL) STRICT;
CREATE TABLE v3_matches (sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 31),
  match_id TEXT NOT NULL UNIQUE, round_no INTEGER NOT NULL CHECK(round_no BETWEEN 1 AND 5),
  year INTEGER NOT NULL CHECK(year=2027),
  record_kind TEXT NOT NULL CHECK(record_kind='fictional_bracket_tournament'),
  namespace TEXT NOT NULL, day TEXT NOT NULL,
  input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL,
  result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL,
  previous_chain_sha256 TEXT NOT NULL, chain_sha256 TEXT NOT NULL UNIQUE) STRICT;
CREATE TABLE v3_advancement (...);   -- v2と同じ列。BYE行は作成時、WINNER行は各試合のtransactionで1行
CREATE TABLE v3_players (...);       -- v2と同じ列＋ CREATE INDEX v3_players_match ON v3_players(match_id)
CREATE TABLE v3_ranks (...);         -- 決勝と同じtransactionでのみ32行（v2同様）
CREATE TABLE v3_acceptance (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  champion_team_id TEXT NOT NULL, games INTEGER NOT NULL, chain_sha256 TEXT NOT NULL) STRICT;
-- 全表にv2同様のUPDATE/DELETE拒否trigger。v2の bracket_checkpoints は chain 列へ統合する。
```

- chain：`chain_i = SHA-256("kokosim-v3-chain\0" ‖ chain_{i-1} ‖ input_sha256_i ‖ result_sha256_i)`、`chain_0 = SHA-256("kokosim-v3-chain\0" ‖ contract_sha256)`。
  入力の `previous_results_sha256` は `chain_{i-1}` とする。1試合あたりO(1)で、v2のO(i)直列化（§1.2）を除く。
  v2と同じ「全結果listのSHA」を残したい場合は、`'[' + ','.join(各結果の正規化JSON) + ']'` を逐次ハッシュしてO(1)で同値を得られる
  （[補助計測] 合成50件で各prefixのSHAが `_sha(list)` と一致）。どちらを採るかはレビュー論点とする（§13）。
- chainは整合性の検査値であり真正性の根拠ではない（W2）。
- 監査ログ・trusted digest・PIDはDBに書かない（決定性の維持、§3.1）。

### 5.3 規模の上限

Stage119-Cのv3は `fictional_bracket.MAX_SIZE=32`（変更しない）に合わせ、31試合・5ラウンドを上限とする。
31試合を超える差分検証の振る舞いは、bracketを使わない**計測専用の合成ハーネス**（§9.2）で確認し、製品・架空大会の保存とは区別して報告する。

## 6. 派生表の差分導出と独立oracle [設計]

1試合のappendで書く行：

|表|差分で書く行|導出元|
|---|---|---|
|`v3_matches`|1行|新しい入力・結果、chain|
|`v3_advancement`|WINNER 1行|`progression(plan, request, trusted_results + (result,))` の差集合（純関数、再計算なし）|
|`v3_players`|新しい試合のeventsの打者・投手×entry team|新しい結果のみ|
|`v3_ranks`・`v3_acceptance`|決勝のときだけ32行・1行|`progression` と `Bracket.ranks` の2系統一致|

合同チームの勝敗はentry teamにだけ属し、構成校の単独勝敗へ加算しない（v2・Stage118の規則をそのまま維持）。
選手・学校の永久IDは出典の `saved_authority` が返す値のみを使い、v3で新しいIDを作らない。投打個人成績Aは結果JSON内に保持し、派生集計表は作らない。

`full_audit` は差分導出のコードを**呼ばない**別実装とする：全結果をdecodeし、各試合の入力を最初から組み立て、全試合を同seedで再計算＋`event_oracle`、
`progression`・`Bracket` の2系統で進出・順位を導出し、全表を `SELECT *` して比較する（v2 `_rows` の構成を、O(N²)直列化を除いて踏襲）。
試験では毎append後に「差分で書いた全表 ＝ `full_audit` の期待行」を確認する（119-Cの受入条件）。

## 7. transaction原子性・反復投入・故障 [設計]

- 1試合1 commit、`BEGIN IMMEDIATE`、`synchronous=FULL`、DELETE journal。接続は操作ごとに開閉する（Windowsでhandleを確実に解放するため。leaseとpinは保持）。
- **WALは採用しない**：`-wal`/`-shm` のsidecarが常駐し、DBファイル単体のbytes digestが内容を表さなくなる。既存の「未知sidecarは接続前に拒否」と両立しない。
- 再送：同一sequence・同一結果は `False`（DB不変）、異なる結果・飛ばし・日付順違い・別scenario・別namespaceの入力は拒否。fast pathではメモリの検証済み列と比較し、DBに触れない。
- commit直後の強制終了・ACK消失：再開の `full_audit` 後にN+1試合が見え、同一再送は `False`。anchorはACKを受けた時点のものなので、N+1 ≥ anchorで受理される。
- commit直前の強制終了：hot journalが残る。v2同様、接続前に拒否し、DB・journalを変更しない（自動復旧しない、W5）。
- commit後の読戻し・digest取得で例外：DBにはcommit済み、stateは `REVOKED`。呼出側は `full_audit` 後に冪等再送で確定できる。

## 8. 旧版互換と対照比較 [設計]

### 8.1 v1/v2の不変性

- `saved_fictional_tournament.py`・`saved_fictional_bracket.py`・`fictional_scenario_history.py`・`fictional_bracket*.py` と既存テスト・workflowは変更しない。
  119-Cでは `git show 86dee10:<file>` とのbytes一致を試験で確認する（Stage118と同じ方式）。
- 既存v1/v2 DBは、既存のクラスでread-onlyに開けることを独立に検証する（v3コードはv1/v2 DBを開かない・書かない）。
- v3の根にv2ファイルがある、v2の根にv3ファイルがある、`application_id` 0のDBをv3として開く、v2のcapabilityをv3の `resume` に渡す――をすべて拒否する。

### 8.2 v2との内容比較（oracle）

結果の `input_sha256` は入力（契約SHA・前結果値・版名）に依存するので、v2とv3の結果JSONはbytes一致しない（[ソース] `registered_match_driver._run` 188行）。
そこで同じ2teamと同じmatch seedを与えた試合について、`input_sha256` を除く内容（全event・イニング・得点・勝敗・打撃/投手個人成績・`run_seed`・確率設定SHA）が
v2経路とv3経路で一致することを確認する。scope・match_idが異なると乱数ラベル（`lab105:{match_id}:pa:{n}`）が変わるため、
この比較はv3の計画を介さず、同一の `BracketMatchInput` 相当を両経路の検証関数へ与える単体比較として行う。

## 9. 性能・容量の計測計画 [設計]（値は[119-C]）

### 9.1 対象と指標

同一環境・同一出典fixture・同一要求で、v2とv3を分離して計測する。

|ケース|指標|
|---|---|
|16team／15試合、32team／31試合|初回作成、1件目append、50%到達時append、末尾append（決勝＝full audit込み）、再開時 `full_audit`、`snapshot`、DB容量（bytes・ページ数・表別行数）、親process CPU、子process最大RSS|
|fast pathの内訳|guard、出典digest、DB digest（書込み前・後）、新試合の検証、`progression`、INSERT、commit、読戻し|
|失効と再監査|`K` 到達、例外後、決勝前のfull audit所要|

v2の基準値は、Stage118の[実測JSON](stage43g118_linux_measurement_20261018.json)をそのまま比較に使わず、119-Cで同じrunnerにより再計測する。
**旧比の改善率は、同一条件の実測が揃うまで書かない。**

### 9.2 合成ハーネス

`Bracket` を使わず、架空の決定的な結果列（明示的に合成と表示）をN=31・64・128・256件追記し、chain・digest照合・差分行導出・`full_audit` 相当の
所要がNに対してどう増えるかを確認する。fixtureは一時ディレクトリだけに作り、製品・架空大会の保存とは混ぜない。
受入条件は「fast path 1件の所要が保存済み件数に対してbytes digest以外で増えない」「全件再監査がO(N)」の2点で、閾値の秒数は事前に決めない。

### 9.3 CI配置

実規模ケースは `test_` で始まらないファイルに置き、全unittest（Stage118 PR時点の実ログで約104分／上限120分）に直列追加しない。
専用workflow（ubuntu／windowsの並行2job）で実行し、全unittestには高速な契約テスト（DDL・状態遷移・失効条件の単体、workflowの配線検査）だけを入れる。
Stage119-Aの計時JSON（`stage43g119_ci_metrics.py`）で、全unittestの所要が増えていないことを確認する。

## 10. SQLiteの長期設計 [設計]

- **分割の単位**：1大会（scenario）＝1 DBファイル。年度ごとのディレクトリにまとめ、年度封印時に各DBのSHA・試合数・chain headを並べたmanifestを作る（manifest自体の設計・実装は後続Stage）。
- **書込み経路**：v3の `append` のみ。必ずTRUSTEDのfast pathか `full_audit` 付き。
- **読取経路**：完了・封印済みの大会は、封印時に `full_audit` を通したbytes SHAとの照合だけで読む（再導出しない）。未完了の大会の閲覧は、そのstoreの `snapshot`（TRUSTEDならfast）を使う。
- **索引**：`v3_matches(sequence)`・`match_id UNIQUE`・`v3_players` 主キー（player_id先頭）＋ `match_id` 索引。
  `EXPLAIN QUERY PLAN` で主要クエリ（選手別出場・試合別出場・試合範囲）が索引を使うことを契約テストで固定する。
- 全国約3,000校・長期の履歴索引（学校・選手横断）はv3大会DBには持たせず、封印済みファイル群から作る読取専用索引として後続Stageで検証する。

## 11. 反例・安全な拒否のマトリクス [設計]（119-Cで全件を試験にする）

|改ざん・故障|v2|v3 fast path|v3 full audit|期待結果|
|---|---|---|---|---|
|DBヘッダ破壊・journal形式変更|拒否|ヘッダ照合・digest不一致→REVOKED|拒否|拒否、bytes不変|
|DDL・trigger削除、未知表・外部表追加|拒否|digest不一致→REVOKED|schema不一致で拒否|拒否|
|checkpoint/chain行の捏造（SHA再計算あり）|拒否|digest不一致|chain・再計算不一致|拒否|
|結果JSONとSHAの同時書換え|拒否|digest不一致|同seed再計算不一致|拒否|
|出場索引の追加・削除・付替え|拒否|digest不一致|全表比較で拒否|拒否|
|古いDBへのすり替え（別inode）|identityで拒否|identity不一致|—|拒否|
|古いbytesを同じinodeへ書戻し|**受理（W1）**|digest不一致→REVOKED|prefixとしては正当|anchorがあれば `resume` で拒否、無ければ検出不能と明記|
|途中失敗の一部反映|transactionで不発生|transactionで不発生|—|全か無か|
|commit直前kill（hot journal）|拒否|sidecar検出→REVOKED|接続前に拒否|拒否、自動復旧なし|
|commit直後kill・ACK消失|冪等|再開でfull audit|N+1を受理|同一再送は `False`|
|別save・別scenarioのcapability|拒否|—|契約不一致で拒否|拒否|
|v1/v2 DB・capabilityの混用|—|—|名前・application_id・型で拒否|拒否|
|出典ファイルの改変|拒否|出典digest不一致→REVOKED|出典再検証で拒否|拒否|
|fork後の子でのappend|—|PID不一致→REVOKED|—|拒否|
|commitと読戻しの間の生書込み|次操作で検出|検出できない窓（§3.3）|決勝前・再開時に検出|完了受理には到達しない|

「強度が下がる状態を暗黙に許す」経路を作らないため、REVOKEDでの自動full auditや、検査失敗時の黙った再試行はしない。

## 12. Stage119-Cの実装タスク表

|#|タスク|成果物|受入|
|---|---|---|---|
|C1|v3モジュール新設（定数・DDL・ヘッダ識別・guard）|`phase2_engine/saved_fictional_bracket_v3.py`|v1/v2ファイルのbytes不変、v2/v3相互拒否|
|C2|`full_audit`（独立導出）|同上|v2と同等の改ざん検出、O(N²)直列化なし|
|C3|状態機械・trusted digest・出典digest・失効条件1〜8|同上|各失効条件ごとの単体試験|
|C4|fast path append・`play_next`・冪等再送・決勝前full audit|同上|毎append後に差分表＝full audit期待行|
|C5|`AppendReceipt`・anchor付き `resume`|同上|同inode書戻しの拒否、anchor無しの限界を試験で明示|
|C6|故障系（子process kill：commit前後、ACK消失、hot journal、Windows handle）|`tests/stage43g119_*`|§11のマトリクス全行|
|C7|v2との内容比較oracle|試験|§8.2の一致|
|C8|v3履歴の読取関数（v2の `scenario_history` は変更しない）|新規読取モジュール|合同勝敗の分離、永久ID|
|C9|計測：v2/v3同条件、合成ハーネス|監査CLI・JSON・報告書|§9の全指標、改善率は実測のみ|
|C10|CI：専用workflow（Linux/Windows並行）、契約テスト|workflow・`test_stage43g119c_contract.py`|全unittest所要の増加なしをStage119-A計時JSONで確認|

## 13. レビューで決めてほしい論点

1. chainの定義：v3独自chain（推奨）か、v2互換の「全結果listのSHA」を逐次ハッシュで保つか。
2. 失効条件1：入力拒否の例外でもtrustを失効させる（推奨・単純）か、DBに触れない拒否は失効させないか。
3. 上限 `K`（fast path appendの連続数）の初期値。暫定8、119-Cの計測後に固定。
4. anchor（`AppendReceipt`）の保持を呼出側の責務にしてよいか。製品統合時にどこへ置くかは後続Stage。
5. 決勝前のfull auditに加え、各ラウンド境界でもfull auditを強制するか。
