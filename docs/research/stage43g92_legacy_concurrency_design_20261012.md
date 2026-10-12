# Stage43G-92：旧Aの試合追加・年度封印を単一transactionへ直列化

2026-10-12（日本時間）、Issue #239。基点はPR #238のマージ後の最新main `6c3132b84e3ade25973afec8ac0fcef6ed3d8317`。旧Aの単一SQLite内のP1修正であり、[ADR-032](../adr/ADR-032-production-save-inventory-adoption-proposal.md)はProposedのまま。保存schema、バックアップ方式、世代manifest、共通slot lock、正式GUI、永久保持履歴の削除・移行は導入しない。旧A ISO日付と架空v2のG論理日付は分離したまま、ゲーム年数の新上限は設けない。

## 調査した保存・呼出し経路

| 経路 | 実際の境界と修正の適用 |
|---|---|
| `HistoricalMatchArchive._connect` | SQLite標準timeout 5秒・Row接続。PythonのConnection contextはcommit/rollbackを行うがcloseしない。新しい内部`_connection`が外側contextの終了後に必ずcloseする。既存の`_connect`返却型とfixtureの接続差替え互換は維持 |
| `sync` | 入力全行を先に正規化して重複key・得点・完全Aを検証。その後schema初期化、writer予約、archive identity・年度seed/plan/resolver・status・既存SHAの確認、必要な行のINSERT、commit。例外は全INSERT/identity/年度行をrollback |
| `seal_year` / `_ledger` | writer予約後に年度状態と全行の順序付きSHAを読み、件数照合と封印UPDATEを同一transactionで行う。sealed再封印は保存件数/ledgerまで照合。`_ledger`の式と保存形式は変更しない |
| `register_next_year` | writer予約後に既存年度identityと最新隣接前年のsealed状態を確認しINSERT。初期・年度出典競合、同じ登録の二重INSERTも直列化。同じmetadataの再登録は成功、異なるmetadataは明示拒否 |
| `LiveGameService.save_game` / `load_game` / `finalize_season` | manual/autosave JSON・slot metadata保存→旧A同期。loadは互換性検証・replay→旧A再同期。年末はreadiness→manual保存＋sync→正確なcompleted件数でseal。変更するのは呼ばれる旧A API内部だけ |
| `live_season_save` / `SaveSlotManager` | schema/checksum/plan/結果/runtime検証、processed date replay、JSON `.tmp` replace、既存manual/autosave各3backup rotationを確認。これらのコードやsave schemaは変更しない |
| career checkpoint | single previewの`_register/_sync`、multiの年度登録・`_sync`、regional/神奈川の`_sync`が同じ旧A APIを使用。前年度outcomes・roster・feeder/選択証拠の照合契約は維持 |
| 履歴閲覧・架空v2 | 旧A school/game読取は既存のquery/順序/payload。`get_match/list_matches/list_years`も接続を明示closeする。架空v2 writer/calendar/indexは独立し今回のtransactionへ参加しない |

## 修正前の確定的再現

最初にmainのStage91 `test_old_a_sync_seal_interleaving_exposes_ledger_breach_and_inventory_refuses`をTemporaryDirectoryだけで実行した。2テスト成功は**欠陥を観測するassertionの成功**である。保存済みM1に対し、別connectionのsync(M1,M2)を年度status取得直後・最初のwrite前のEventで停止し、seal(expected=1)を完了してからsyncを再開する。旧処理は二つのAPIが成功して、`historical_matches=2`、`career_years=(sealed,1)`となる。read-only inventoryは封印ledger不整合を拒否した。

`with conn`に入るだけでは読取り前にtransactionを開始しない。旧syncはactive判定を保存したままsealのcommitをまたぎ、後続のINSERTで初めて暗黙transactionを開始する。seal側もledger読取りとUPDATEの間が同じread→write競合だった。年度登録も「未登録」読取りとINSERTが分離し、同時登録は同内容でも一方がraw UNIQUEエラーとなり得た。

## 最小の修正とtransaction境界

三つのwrite APIで次の順序を固定する。

```text
入力検証 → connection取得 → executescript(_SCHEMA)
        → with conn → BEGIN IMMEDIATE
        → identity / 年度 / 重複 / ledger の読取り
        → INSERT または封印UPDATE / idempotent結果決定
        → commit（失敗ならrollback） → 外側context終了 → close
```

`executescript(_SCHEMA)`は暗黙COMMITを伴うため、**BEGINの後には呼ばない**。既存schemaのCREATE IF NOT EXISTSが終了してからwriterを予約する。DDLと最初の新規DB作成自体を一括rollbackする契約は追加しない。schemaは以前と完全に同じ文字列であり、新規identity/年度/試合のtransaction失敗は空の既存schemaを残して全DMLをrollbackする。

予約はSQLiteのDB単位writer lockである。同一DBの別接続・別archiveインスタンスでも三つのAPIは決定読取りへ同時に入れない。入力正規化はlock前のままとし、予約中の時間を増やす不要な作業を入れない。検証済み同内容のsealed同期もwriter予約を取得するが、既存行/ledgerをUPDATEしない。

| 先行操作 | 後続操作の安全な期待値 |
|---|---|
| syncがM2追加 | seal(expected=1)は実2件を見て明示拒否。activeのまま保持し、expected=2でsealできる |
| syncがM2追加 | seal(expected=2)は追加commit後の2件を含む正しいledgerで成功 |
| seal(expected=1) | 新規M2同期はsealedを見て拒否。既存M1同内容だけの同期は成功 |
| 同時同内容sync | 最初だけINSERT、後続は同SHAを認めalready_archived。改変は拒否 |
| 同時seal | 最初が封印、後続は同じ件数/ledgerでalready_sealed |
| seal→次年度登録 | 登録はsealのcommitを待ち隣接前年sealedを確認して成功 |
| 登録→seal | 未封印前年への登録は拒否、sealは成功。登録は明示再試行で成功 |
| 同時次年度登録 | 同identityならregistered=True/Falseで成功。別seed/planなら後続を拒否 |
| 次年度登録→sync | syncは登録を待ち明示登録された年度へ追加。sync先行は未登録として拒否し、登録後に再試行 |

## 独立fixture・oracleと回帰の更新

Stage91の旧不具合を許容するテストを安全な期待値へ置換する。名前も保護成功を示し、旧assertionを残さない。別のsource-free新fixtureでWAL/DELETEを設定し、Connection subclassのSQL境界とEventで先行readを停止、後続BEGINの試行を観測する。独立zero-timeout connectionが`BEGIN IMMEDIATE`を拒否されることで予約を確認する。sleepによる順序指定、production test hook、daemon thread、同connection共有を使わない。finallyでEventを解放し全threadをjoin、全handleがclosedであることを確認する。

oracleは製品`_ledger/_canonical/_history_payload`を呼ばず、別接続で行順・payload SHA・各key・年度件数・独立計算したledgerを照合する。sealed再同期・改変拒否・部分batch失敗ではDB本体のbyte比較と全正本table比較を行う。初期identity/年度/試合INSERT、seal UPDATE、次年度INSERTの直後へ注入した例外でもrollbackとcloseを証明する。

実liveの縮小した既存annual planを完了し、manual/autosave、replay、finalize、sealed後のmanual/autosave/古いmanual backup loadを行う。前後でhistory・live JSON・roster・独立v2ファイルのSHAを照合。これは実ゲーム経路の検証であり、合成v2 fixtureを連続ゲームの年度進行とは表示しない。関東8都県17校E2Eは既存の完全経路を別実行する。

## lock・timeoutと保証の限界

SQLite標準`busy_timeout=5000ms`を維持し、新しいretryや自動fallbackを追加しない。後続writerは最大約5秒待って`sqlite3.OperationalError: database is locked`を呼出し元へ返すことがある。短い50ms timeoutをfixtureだけで使用し、3 APIが一切DMLしないこと、close後にlockを解放して明示再試行できることを検証する。WALはreaderとwriterを併用できるがwriterは1つ。DELETE journalではreaderによってcommitが待たされる可能性も従来通りある。

保護対象はこの3 APIによる同じ旧A DB内のread→write判断である。外部raw SQL改変、ファイル置換、複数DB＋JSON集合の同時点保証、roster/outcome/checkpointとの原子公開は追加しない。JSONが先行する既存save手順は残り、sync拒否後にJSONが追加履歴を含む場合は既存互換性検証/明示ロードで拒否し得る。封印済み履歴を自動巻戻し・自動修復しない。過去年の保持と出典を優先する。

専用CIはLinux/Windowsの旧A21テスト・52条件とStage91 inventory、Linux/XvfbのStage89 v2・旧A学校閲覧・実Tkを実行する。既存Python workflowで全Python 3.12 unittestと関東17校E2Eも別jobとして実行し、すべて成功後もPRを未マージ・auto-mergeなしでレビューへ提出する。
