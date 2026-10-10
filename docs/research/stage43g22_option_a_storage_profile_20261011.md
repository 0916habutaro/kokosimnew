# Stage 43G-22：A方式保存容量の内訳・SQLite索引ページ・20年／50年性能監査

作成日：2026-10-11。前工程 Stage43G-21 PR #162 は全CI成功を確認し main にマージ済み。

## 目的
Stage43G-21は2校×10年でA方式の試合原本・キャリア年度ロスター・派生キャッシュの計3DBの実測値を確認した。本工程では、**A方式試合のどの情報が容量を占めるか**を実際に保存されたJSONから分析し、同じ安全な合成基盤で20年・50年まで測定する。元のセーブ形式、正規の試合内容、保存済み年度台帳、派生キャッシュはいっさい改変しない。

## 実装
- `phase2_engine/career_option_a_storage_profile.py`：保存済み`historical_matches.payload_json`全行を読み、DB上の`record_sha256`と照合してからUTF-8バイト数を集計。
- JSON内訳は`inning_scores`、`team_stats`、`batter_stats`、`pitcher_stats`の**値をcanonical JSON表現で再エンコードしたバイト数**と、その他キー名・区切り構文・メタデータ値の残余容量を合計する。合計と元payloadの完全一致を検査。ただしこれはJSON文字列の内訳であり、SQLite本体のテーブル/索引ページ使用量ではない。
- SQLiteの`page_size`、`page_count`、`freelist_count`を3DBごとに収集。使える環境では`dbstat`の`name,SUM(pgsize)`によりテーブルと索引のページ容量を表示。SQLiteビルドでdbstat未対応なら利用不可として報告する。
- `gzip.compress(mtime=0)`で先頭最大100試合の保存済みJSONを**一試合ずつ仮圧縮**し、元のUTF-8バイト数との比率を報告。gzipは実ファイルやゲーム保存形式に適用せず、SQLiteインデックス・ファイルヘッダ・ページ空き領域の削減率にも換算しない。
- `run_full_a_benchmark`に`storage_profile`を接続し、従来からの年度別ロスター保存／A方式試合SHA・選手ID帰属／封印年度キャッシュ／原本とキャッシュ集計一致／3DB読取前後SHA一致を維持。
- プロファイラーは既存ファイル以外をSQLite接続せず、`mode=ro`かつ`PRAGMA query_only=ON`。不存在DBは自動生成せず拒否する。

## 自動テスト
`tests/test_stage43g22_option_a_storage_profile.py`：
1. 2校×3年、全A方式の試合件数、イニング・チーム・打者・投手・メタデータJSONのバイト内訳が実payloadと一致
2. 3DB実容量が前工程の容量計測と一致し、対応可能なSQLiteではdbstatオブジェクト別ページも算出
3. 計測前後の原本・ロスター・キャッシュSHAが不変
4. 元試合のSHAが変更されていた場合、診断成功として扱わず失敗
5. gzip sample=0など任意サンプル・入力不正・不存在DBの新規作成拒否

## CIの測定条件
`.github/workflows/option-a-storage-profile.yml`：
- **2校×20年×各校年2試合（合計40試合）**を測定
- **2校×50年×各校年2試合（合計100試合）**を測定
- 実際のゲームの全国大会や県・地区予選を実行するのではなく、Stage43G-21の合成対戦と学校年度ロスター・保存済み選手IDで生成。毎年のロスター交代と年度別成績キャッシュを含む。
- 各結果は実測JSONをログ出力し、30日保管のGitHub Actions artifactに記録する。測定値・マージ状況はCI結果が確認できてからPR本文／コメントに追記する。

例：

```sh
python -m phase2_engine.career_full_a_benchmark --data-root data --schools 2 --years 50 --games-per-school-year 2 --repeats 2 --output-json full-a-storage-50y.json
```

## 前工程との比較上の注意
Stage43G-20の24校×100年ベースラインは試合スコアのみ。Stage43G-21の2校×10年は打席イベントの保存なしA方式、学校年度ロスターと派生個人成績キャッシュあり。本Stageではそれらを区別し、保存形式やサンプル校数が異なる値を無条件に容量倍率・無制限年数への性能保証として扱わない。

## 未完成・次候補
本フェーズは**2校×20/50年の読み取り専用容量・性能監査**であり、全国3,000校×50年／100年の計300,000学校年度の完全ロスター・A方式試合・キャッシュ実測ではない。試合エンジンの完全な大会日程・年数無制限の実行確認、正式GUIでのWindows表示、実試合数に基づく大容量ストレス計測は引き続き未検証。

Stage43G-23候補：測定結果から個人成績キャッシュ・ロスター・A方式JSONそれぞれの大容量要因を整理し、索引最適化・圧縮案を**元の保存契約を変えず比較検討**、長期セーブの増分データ管理と無制限年数設計を文書化する。
