# Stage 43G-119-A：全unittest実行時間・CI安定化の観測設計（2026-10-18）

対象：[Issue #293](https://github.com/0916habutaro/kokosimnew/issues/293)。起点main: `04da66e277ca3a6a013fcb2a61811baadd2f9d5a`（Stage118完了、46/46 check成功）。

## 本Stageの目的と非対象

大規模な保存／強制終了／旧版互換テストを除外・省略せず、**従来の unittest discover と同じ約2,400件を一度だけ実行**し、test ID・module別の所要時間と公開可能なrunnerメタデータを保存する。

- 変更対象はテスト実行ラッパ、合成契約テスト、Python CI workflowのみ。試合計算・Stage116 v1・Stage117 v2・Stage118のv2利用コード・本番書き込み・既存ユーザーsave・masterは変更しない。
- 既存の`KOKOSIM_SKIP_STAGE43G10_E2E=1`、`timeout-minutes: 120`、関東17校E2E独立job、Stage118専用Linux/Windows jobを維持。
- テスト速度改善、原因確定、v3保存実装、50/100年履歴性能検証を**達成したとは主張しない**。

## 既存実ログからの基準値（本Stage以前の事後集計）

| ジョブ | Stage117 main `2cec50c` | Stage118 PR `81ec994` | 増減 |
|---|---:|---:|---:|
| Python 3.12全unittest | 2432件／4619.347秒（約77分） | 2437件／6233.720秒（約104分） | +1614.373秒 |
| Windows年次 | 65分44秒 | 63分07秒 | −2分37秒 |
| 関東17校E2E | 6分45秒 | 8分27秒 | +1分42秒 |
| Stage118専用Linux／Windows | 未導入 | 27分24秒／33分00秒 | 2job／約60 runner分 |

GitHubのtest行終了時刻差による分析では、既存モジュールのうち `test_stage43g117_bracket` が約+272秒、`test_stage43g116_tournament` が約+166秒、`test_stage43g102_master_scale` が約+99秒、`test_stage43g96_continuation` が約+91秒など多数が増加した。一方、新規5テストの所要は合計約5秒。

両CIのrunner imageバージョンは同系統だが、runner実体とAzureリージョンが異なる（westus3 / northcentralus）。**ランナー性能差を原因と断定する根拠はまだない**。この事後集計はログ出力行のタイムスタンプ差からの近似で、今回からの`perf_counter`による計測値とはそのまま厳密比較しない。

## 追加した仕組み

- `tests/stage43g119_ci_metrics.py`：同じ`unittest.TestLoader.discover(start_dir=tests, pattern=test*.py, top_level_dir=tests)`。既存の詳細出力とテスト判定を維持。
- `TimedTextResult`：テストごとにwall（`time.perf_counter`）と親PythonプロセスCPU（`time.process_time`）を収集。CPU値は子processのCPUを含まず、wallと一致するとは限らない。
- スキップ・成功・失敗・エラー・expected failure・unexpected success・subTest失敗を分類。すべてのdiscovered test IDが報告に存在することを検査する。
- CI出力：`audit-results/unittest-timings.json`。schema=1、実行数・skip数・wall/CPU、全テスト・module別の所要、環境の公開可能なホワイトリスト情報。マシン名、環境変数全量、認証情報、元saveは記録しない。
- `GITHUB_STEP_SUMMARY`に実行時間上位12モジュールと120分制限の残りを表示する。110分超なら警告するが、**観測結果だけを理由に本来成功したCIを失敗させない**。
- `actions/upload-artifact`の`if: always()`で、通常のテスト失敗でも出力済みJSONを保存する（timeoutでjob自体がkillされた場合は保存不可）。
- `compare_reports`：schemaが同一の2JSON間で共通ID・追加・消滅・テスト別差分とmodule別差分、runnerメタデータを出力する。比較だけでは因果関係は判定しない。

### 実行例

通常のCIと同じ全件実行（開発PCでは環境により非常に長い）：

```bash
KOKOSIM_SKIP_STAGE43G10_E2E=1 python tests/stage43g119_ci_metrics.py --json-output audit-results/unittest-timings.json
```

2回分のCI artifactをローカル取得後に比較：

```bash
python tests/stage43g119_ci_metrics.py --compare-base before.json --compare-current after.json --json-output diff.json
```

`--json-output`は既存ファイルがある場合に上書きを拒否する。以前のStage117/118はJSONを残していないため、今回以降に集める**同じschemaのJSON同士**が定量比較の正本になる。

## 受入条件・作業上の留意

1. 合成ケースで、成功・失敗・skip・subTest・テストID・モジュール集計・環境ホワイトリスト・比較・出力上書き拒否を確認する。
2. 全unittestは一度だけ実行し、既存成功失敗判定を保持。新規高速テストのみ追加し、テスト総数は今回の新規分だけ増える。
3. 検証は既存CI全件 + Stage118専用Linux/Windows全件で、数・実行時間・skip数を報告する。
4. 120分が近い／超過した場合は、**テストを削らず**後続Stageでジョブ分割や上限調整を検討する。
5. PRは日本語で作成し、全チェック成功後も未マージ・auto-merge無効・レビュー待ちで停止する。mainマージにはユーザー承認が必要。

## 次Stageの課題

Stage119-B/CでStage117-v2の既存prefix再導出（保存回数×N、合計O(N²)）をv3差分検証に置き換える**設計・実装・故障時監査**を別PRで行う。先に長期年数を実測したり公式2027参加・順位・日付を確定したりしない。

## 2026-10-18：実CIで発見した重複IDへの対応

PR #294の初回head `c066538` の全unittestは **2,443件・skip 57・約6,087秒・エラー0**で成功し、JSON artifact `stage119a-full-unittest-timings` も保存された。ただし、実計測データに**同一 `unittest.TestCase.id()` を複数回使う行が75件**存在することが判明した。これは実行インスタンスの反復であり、Python unittestの成功判定と矛盾しない。初版 `compare_reports` は重複を一律拒否するため、そのままではこのJSONを比較できなかった。

修正方針：
- 各テスト終了時、同一 `id` について出現順に **1始まりの `occurrence`** を付与し、`(id, occurrence)` を一意な比較キーにする。テスト数、skip・成功、元の実行順・実行回数は変えない。
- 初回CIの **schema=1、`occurrence` フィールドなし**のJSONでは、格納された `per_test` の行順から `occurrence` を再構築できる。初版のartifactは破棄・書換え・再取得不要。
- 不正な `occurrence`（重複、0、欠番、真偽値、非整数）やレポート `tests` と記録行数の不一致は拒否する。
- `test_deltas` は `id` と `occurrence` を分離して返し、`added_instances`／`removed_instances` にも同じ構造を保存する。従来の文字列 `added_tests`／`removed_tests` は初回出現時そのまま、2回目以降は `#2` 等の接尾辞で区別する。
- 出現順が異なる場合に同じ名称のn回目同士を対応させるため、**同一IDの実行順が比較対象の間で安定していることが前提**。独立したテストの一意IDを推測する仕組みではない。異なる順序での比較は因果・同一インスタンス同定を保証しない。
- 合成テストで同じIDの反復実行、初回artifact互換、追加・削除された発生回、重複ordinal／欠番／型不正拒否を検証する。エンジン・旧テスト内容・全unittestのtimeoutは変更しない。

**受入条件**：最終headの全CIが成功し、最終JSONを初版の重複ID付きJSONと `compare_reports` で比較できることを確認した後にのみマージを判断する。今回の修正はCIの速度そのものを改善するものではない。
