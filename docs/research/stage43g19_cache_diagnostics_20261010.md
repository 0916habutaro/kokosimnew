# Stage 43G-19：長期履歴のキャッシュ診断と実測ベンチマーク

作成日：2026-10-10。前工程 Stage43G-18 PR #159 を前提とする。

## 目的

3,000校超の高校野球キャリア履歴を数十年から100年以上読み取る際、ゲームのスロットに残したA方式試合・選手ロスター・派生キャッシュのどこに欠損や不一致があるかをGUIから調べられるようにする。**診断は変更・再生成・修復を実施しない**。実測した性能だけを記録し、全国3,000校×100年規模の性能が確認済みとは表示しない。

## 追加したインターフェース

- `phase2_engine/career_history_cache_diagnostics.py` の `CareerHistoryCacheDiagnostics.report(school_id, start_year, end_year, check_cached_rows=True)`：選択した学校の年度範囲だけを閲覧。原本のcareer_years、派生キャッシュの学校年度集計と選手年度件数をSQLite `mode=ro` で取得
- 追加の診断状態：`cache_ready`、`cache_missing`、`source_active`、`source_missing`、`cache_source_mismatch`、`cache_corrupt`、`cache_on_unsealed_source`、`cache_without_source`、`orphan_cache_rows`、`cache_unreadable`、`cache_metadata_matches`
- `check_cached_rows=True`：Stage43G-15/18の全候補行SHA・校年度件数・fact SHA検証を実行。高速診断`False`では封印台帳メタデータとの一致だけを検査し、`cache_metadata_matches`と表記する
- `CareerHistoryGuiPilot` に「キャッシュ診断」ボタン。選択学校・表示年度までの範囲をJSON詳細欄に示す。戻り履歴・元セーブを変更しない
- `benchmark(..., repeats=1..10)`：同じ学校・スロット・年度範囲の診断時間を`perf_counter`、Pythonメモリピークを`tracemalloc`でその場で測定し、実測値と`measurement_scope=one_local_slot_one_school`を出力

CLI例（実際に保存したスロットを指定）：

```sh
python -m phase2_engine.career_history_cache_diagnostics --data-root data --slot <slot-dir> --school-id <school-id> --start-year 2026 --end-year 2125 --repeats 3
```

対象年度は一度に最大500年度。多年度でも全試合をメモリに読み込まない。ただし完全行検証時は各校年度の選手派生行を検証するため、実際の負荷はデータ量に依存。

## セーブ安全性と結果の意味

GUI・診断CLIでのDB接続は読み取り専用。キャッシュが存在しなければ新規作成しない。診断のために`materialize`は呼ばない。最新の原本試合データの全件SHAを診断で走査するものではなく、キャッシュ状態・保存済み台帳と派生SHAの整合性を確認する。

報告は`game_career_sandbox_not_official`に限定。未生成キャッシュは正常な未作成状態として区別し、破損を勝手に修復しない。診断が`cache_ready`でも「原本の全試合payload SHAが当日改めて検証済み」とはみなさない。

## 回帰テストと未完了

`tests/test_stage43g19_cache_diagnostics.py` 新規9テスト：
1. 未作成キャッシュを生成せず区別
2. 封印キャッシュ正常時のステータスとDB3ファイルの完全不変
3. 封印台帳SHA不一致
4. キャッシュ行SHA改ざん
5. active年度への偽キャッシュ
6. SQLite破損
7. 学校×年度factを欠く孤児レコード
8. 実測時間・Pythonメモリのみを報告し、全国規模の保証はしない
9. 不正な学校ID・期間・反復数の拒否

Python 3.12全単体テストと関東8都県17校E2Eの両成功確認後にmainへ反映。

未完了：本当に全国3,000校×100年のセーブを生成しての所要時間・ディスク容量・メモリ監査、Windowsでの実GUI表示試験、正式GUIとの統合、ゲーム年数無制限化、キャッシュ修復操作の設計。
