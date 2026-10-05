# Stage 12I 再照合ステータス自動判定 実装報告書

作成日: 2026-10-06

## 目的

Stage 12Iの秋季大会日程再照合を、毎回19大会を手作業で分類する運用から外す。

再照合キューCSVを入力に、指定日を基準として以下を自動判定する。

- next_check_date
- status
- remaining_count
- recheck_reason

## 判定ルール

remaining_planned_dates の最も早い日を next_check_date とする。

- next_check_date < as_of: `recheck_due`
- next_check_date == as_of: `today_pending`
- next_check_date > as_of: `future_pending`
- remaining_planned_dates が空: `complete`

この判定は「試合結果を推測する」ものではなく、公式結果を再確認すべきタイミングを機械的に抽出するための運用補助である。

## 実装

追加:
- `phase2_engine/reconciliation.py`
- `phase2_engine/reconciliation_cli.py`
- `tests/test_stage12i_reconciliation_automation.py`
- `audits/phase2/stage12i/stage12i_recheck_status_20261006.csv`

CLI例:

```bash
python -m phase2_engine.reconciliation_cli \
  --queue audits/phase2/stage12i/stage12i_autumn_reconciliation_queue_20261006.csv \
  --as-of 2026-10-06 \
  --output audits/phase2/stage12i/stage12i_recheck_status_20261006.csv
```

## 2026-10-06時点の結果

- total: 19
- recheck_due: 0
- today_pending: 6
- future_pending: 13
- next_check_date: 2026-10-06

today_pending:
- CMP000091 埼玉
- CMP000120 京都
- CMP000122 大阪
- CMP000134 岡山
- CMP000136 広島
- CMP000148 福岡

## 翌日未更新時の挙動

同じキューを2026-10-07として判定すると、

- recheck_due: 6
- today_pending: 1
- future_pending: 12

となる。

つまり10月6日の6大会について結果更新を忘れた場合でも、自動的に `recheck_due` へ上がる。

## 設計上の境界

この機能は日付と再照合キューだけを使う。

- Web上の結果を自動取得しない
- 試合完了を日付だけで確定しない
- season_calendar.csvを自動変更しない

公式結果の確認後にキューとmasterを更新する責任は従来どおりStage 12Iの調査工程に残す。

## 検証結果

GitHub Actions上で実際に検証した。

- unit test: **143 / 143 PASS**
- reconciliation CLI: **実行成功**
- 2026-10-06 status: **19件 = recheck_due 0 / today_pending 6 / future_pending 13**
- 県大会E2E: **94 / 94 PASS**
- access rules: **22 / 22 PASS**
- calendar gaps: **0**
- internal structure gaps: **0**
- warnings: **0**

最初の検証では、生成器が next_check_date 順に並べる一方、手作成スナップショットが元キュー順だったため比較テストのみ失敗した。スナップショットを実際のCLI出力順へ修正し、再実行で143/143 PASSを確認した。判定ロジックの不具合ではない。

## 次工程

10月6日の試合終了後、CLIで `recheck_due / today_pending` を抽出し、該当6大会の公式結果を再照合する。
