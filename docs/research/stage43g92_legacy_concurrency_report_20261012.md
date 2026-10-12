# Stage43G-92：旧A sync/seal競合の修正・検証報告

2026-10-12（日本時間）、Issue #239。最新main `6c3132b84e3ade25973afec8ac0fcef6ed3d8317` から独立ブランチで実装。[設計書](stage43g92_legacy_concurrency_design_20261012.md)に保存経路、transaction境界と残る競合を記録した。

## 結果と変更

旧Aで両API成功なのに「試合2件／封印ledger1件」となるP1を修正した。`sync/seal_year/register_next_year`がschema初期化後・判断読取り前に`BEGIN IMMEDIATE`を取得する。追加先行では封印側が最新件数を確認し、封印先行では同期側が新規試合を拒否する。sealed同内容sync、同identityの年度登録、旧score-only、Stage43Cの年度tableなし旧archiveの既存backfill契約を維持する。

製品変更は`phase2_engine/historical_match_archive.py`のみ。三つのBEGINと接続closeの所有を追加し、`_SCHEMA`・payload/ledger式・JSON schemaは変更しない。入力検証はlock前、判断とDMLは一transaction、例外はrollback後close。`get_match/list_matches/list_years`も確実にcloseする。

追加・更新したもの：Stage91不具合観測テストの安全な期待値への置換、Stage92独立connection/Event fixtureとoracle、完全A/score-only/rollback/busyの回帰、実live replay/年度終了回帰、fixture-only証跡CLI、Linux/Windows専用CI、日本語設計書・本報告、監査結果JSON/ログ。ADR-032 Proposed、既存manual/autosaveの保存・backup規約、ゲーム年数無制限、ISO旧AとG論理日付v2の分離は維持する。

## 修正前と修正後の再現

mainのStage91再現を修正前に実行し、2テスト成功で旧不整合の発生とinventory拒否を確認した。[修正前ログ](../../audits/phase2/stage43g92/baseline_reproduction_20261012.log)にその実行結果を保持する。現在のテストには不整合を許容するassertionを残していない。

修正後は先行state読取りをEventで停止、別writerのBEGIN試行を観測してから解放する。独立zero-timeout接続がwriter予約を確認する。WAL/DELETEそれぞれでsync→sealとseal→sync、正確/古い件数、重複sync、同時初期identity、同時seal、sealと翌年登録の両順、同時登録の同内容/異出典、登録と翌年syncの両順を検証した。独立oracleは件数・payload SHA・年度status・ordered ledgerを別計算し、全thread終了と接続closeを検証する。

失敗試験は途中INSERT/初期identity/年度登録/封印UPDATEをrollbackし、元行とtable snapshotを維持する。sealedの同内容sync・新規/改変拒否・score-only・部分batch拒否ではDB本体のbyte不変も確認した。正常な新年度追加が旧年度の完全Aを変えないことも確認した。

## 実行結果

| 検証 | 結果 | 証跡 |
|---|---|---|
| Stage92旧A競合＋実live replay | **21テスト成功・52 subtest条件成功、skip 0**、2.253秒 | [JSON](../../audits/phase2/stage43g92/concurrency_20261012.json)、[ログ](../../audits/phase2/stage43g92/concurrency_20261012.log) |
| Stage91 inventory＋更新済み安全境界 | **20テスト成功、skip 0**、0.479秒 | [JSON](../../audits/phase2/stage43g92/inventory_20261012.json) |
| Stage89 v2 concurrency・実Tk | **19テスト成功・54条件成功、skip 0**、11.717秒 | [JSON](../../audits/phase2/stage43g92/v2_regression_20261012.json) |
| Python 3.12全unittest（Xvfb） | **2076テスト成功、失敗/エラー0、skip 2（関東専用2件）**、835.784秒 | 全体ログと検証集計を保管 |
| 関東8都県17校の実ゲームE2E | **2テスト成功、skip 0**、309.167秒 | 予選・第三代表決定・地域大会決勝・途中再ロード・不完全feeder拒否を含む |

全体suiteの関東17校2件は既存CI規約どおり専用jobへ分離する。Stage92専用CIのLinux/Windows各jobは21テスト・52条件、Stage91 20件・skip 0をassertする。Linuxの別jobはXvfbでStage89 19件・54条件と旧A save slots/年度境界/roster/学校閲覧/実Tkを実行し、証跡をartifactとして保存する。既存Python CIの全unittest・関東17校も必須確認する。

ローカルの最初の実Tk実行はsandboxのsocket制限でXvfbへ接続できなかった。Tk起動を確認できる実行条件へ修正して再実行した結果を上表に記載し、画面未検証の成功とは扱っていない。Windowsの実行結果はGitHubの専用matrixで確認する。

## 正本・マスター保護

fixtureはすべて新しいTemporaryDirectoryへ生成し、既存セーブや学校マスターを試験入力・変更対象にしていない。全試験の開始前後に非公開SHAを比較する。公開結果は**master CSV 106ファイルと既存セーブ4ファイルの件数・全内容一致**のみで、利用者pathや実SHA一覧はコミット・PR本文・ログに出さない。

実live fixtureでは、manual/autosave/backupロード前後の全ファイルSHA、封印履歴全行とledger、保存roster、独立v2 calendar/historyのbytesを比較する。既存save JSONのseed/plan/resolver検証・replay、年末readiness、古いcheckpointが新しい履歴を削除しない動作を確認した。v2をliveの年度進行へ接続していない。

## 性能と運用制限

同じ完全A2試合、同じAPI順、fresh DB、両実装のhandleを明示closeし、旧mainと修正後を各journal/各実装40回測定した。Python 3.12.14 / SQLite 3.53.1。競合なし・小さいfixtureのAPI計測であり、全国連続ゲーム性能やSLOではない。[測定JSON](../../audits/phase2/stage43g92/performance_20261012.json)に中央値/p95を保持する。

| journal | API | 修正前→後 中央値(ms) |
|---|---|---:|
| DELETE | 初回sync / 冪等sync / 追加 | 0.615→0.512 / 0.225→0.219 / 0.284→0.251 |
| DELETE | seal / sealed sync / register | 0.231→0.218 / 0.291→0.253 / 0.189→0.181 |
| WAL | 初回sync / 冪等sync / 追加 | 0.467→0.470 / 0.243→0.256 / 0.295→0.321 |
| WAL | seal / sealed sync / register | 0.246→0.221 / 0.279→0.296 / 0.200→0.205 |

数値の微小差やp95のばらつきから高速化・大規模性能を主張しない。冪等syncもwriterを予約し、同じDBの追加/封印/登録は待機する。標準busy timeout **5秒**は維持。fixtureでは50msで3 APIのtimeout拒否・一切DMLなし・closeと明示retry成功を確認した。writer待ちが加わり、DELETEでは既存readerがcommitを待たせる場合がある。大きいsync batchや年末ledger走査の間の長時間writer待ちは未計測であり、自動retry/timeout拡大を追加していない。

## 残る境界と提出状態

修正対象は旧A単一DBでの協調する3 APIに限る。JSON先行保存とarchiveの別commit、roster/outcomes/checkpointの多file同時点、外部raw SQL/DB置換、電源断後の集合復元は別問題として残る。sealed履歴を自動修復・巻戻し・削除しない。新しいバックアップ方式/世代manifest/共通slot lockの採用・移行は今回のP1修正に含めない。

GitHub PRでは最終headの全CI成功を確認し、**未マージ・auto-mergeなし・レビュー待ち**で停止する。PR URLと最終CI結果はPR本文および完了報告へ記載する。
