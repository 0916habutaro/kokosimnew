# Stage 43G-20：50年・100年履歴のSQLite索引／容量／閲覧性能の再現可能な基準計測

作成日：2026-10-10。前工程 Stage43G-19 PR #160 mainマージ済み。

## 目的・現在の検証限界

従来のStage43G-13は100年規模の学校履歴索引を整備し、Stage43G-19は学校・年度を指定したキャッシュ診断の実測処理を追加した。本Stageでは「学校数×年度数×年試合数」を指定して**試合アーカイブを別の一時SQLiteに再現可能な形で生成し、既存の学校履歴read modelを実測**する。

本コードは**全国3,000校×100年を検証済みと主張しない**。ゲームの年次進行ロジック・大会参加校の組み合わせ、選手A方式の打者／投手個人成績生成を行わない。合成データはA方式アーカイブの同じSQLiteテーブル・索引と、試合結果スコアのみを保存する契約を利用する。元試合は同じ`_history_payload`正規化・canonical JSON・SHA-256、年度台帳は`HistoricalMatchArchive._ledger`を用いて封印する。イニング別得点・個人成績の保存が必要な実データのディスク容量に対しては**過小評価側のベースライン**である。

## 実装

`phase2_engine/career_history_scale_benchmark.py`：
- `build_synthetic_archive`：ユーザーのセーブと別の一時領域だけに合成DBを作る。既存ファイルは上書き拒否。学校ID・試合IDは決定的で、年ごとに件数と封印台帳SHAを検査。
- `measure_indexed_history`：Stage43G-12/13の`CareerLongitudinalReadModel.school_results`で、最初・中央・最後の学校IDについて、年度範囲での1ページ30件取得を反復実測。結果はmedian経過ms・繰り返しの経過ms・`tracemalloc`で追跡できたPythonメモリピーク、学校×年度大会の件数とページ行数。
- SQLite索引`idx_history_school1_year`／`idx_history_school2_year`が存在すること、総試合行数が仕様通り、閲覧前後でDB全体のSHA-256が変わらないことを確認。大容量DBは1MBずつ読み、ファイル全体を一度にメモリへ展開しない。
- `run_benchmark`：DBファイルバイト数と合成生成時間を記録し、終了時に一時セーブを削除。学校数・年度数・年試合数・繰返し・元データではないことをJSONに併記。
- 入力上限は最大3,000校、100年、年間50試合（絶対上限500万試合）。通常は合成25万試合を超えない。超過する場合にのみ明示的な`--allow-large`が必要。大規模検証は十分なストレージと時間がある環境のみで実施。
- 上記の`allow-large`があっても絶対上限を超える試験は拒否。

## 実行例

標準の小規模計測（24校×50年×年4試合＝4,800試合）：

```sh
python -m phase2_engine.career_history_scale_benchmark --schools 24 --years 50 --games-per-school-year 4 --repeats 3 --output-json benchmark-50.json
```

100年の基準計測（24校×100年×年4試合＝9,600試合）：

```sh
python -m phase2_engine.career_history_scale_benchmark --schools 24 --years 100 --games-per-school-year 4 --repeats 3 --output-json benchmark-100.json
```

より大きい合成データの任意計測（例：3,000校×100年×年4試合＝120万試合）：

```sh
python -m phase2_engine.career_history_scale_benchmark --schools 3000 --years 100 --games-per-school-year 4 --repeats 3 --allow-large --output-json benchmark-3000x100.json
```

最後のコマンドは**実行サンプルであり、既に測定が完了したわけではない**。時間・ストレージ制限に注意。

## CI・測定値の扱い

`.github/workflows/history-scale-benchmark.yml`を追加し、PR時およびmain反映時に24校×50年・24校×100年を実行する。ログに実測JSONを出力するとともに、GitHub Actions artifact（30日保管）に2つの結果ファイルを保持。実測はRunnerの負荷・OS・Pythonバージョンによるため、絶対的なSLAとしては扱わない。

`tests/test_stage43g20_history_synthetic_scale.py` では、実スキーマ／校別学校読み取り索引／4年分の封印件数・改ざんなしのページ集計、合成DB上書き防止、大きな試験の明示的許可を確認する。

## 未実装と次工程

- 全国3,000校×100年の**実行結果と確認済み数値は未取得**。この段階は安全な負荷試験の実行装置を整える。
- 既存Stage43G-19の診断／キャッシュ、打者・投手の完全Option-A箱スコアを含む実データのストレージ測定は未統合。スコアのみの値を本番保存サイズに外挿しない。
- Stage43G-21候補：個人成績・年度選手ロスター・派生キャッシュを含めた容量と閲覧性能の比較、100年学校データの画面応答時間の分位点、Windows実機GUIでの動作試験。
- 「年数無制限」化には別途、年番号と暦の分離、セーブ設計・年度進行の継続性を実装する必要がある。
