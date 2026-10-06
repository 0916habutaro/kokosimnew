# Stage 12O checkpoint駆動の再照合キュー自動生成

作成日: 2026-10-07

## 目的

Stage 12Nで作成した `autumn_recheck_calendar.csv` を、実際の再照合作業で直接利用できるようにする。

指定日を渡すと、その日までに確認すべき追跡行だけを抽出する。

## 実装

追加モジュール:

- `phase2_engine/recheck_calendar.py`
- `phase2_engine/recheck_calendar_cli.py`

CLI:

```bash
python -m phase2_engine.recheck_calendar_cli \
  --calendar data/schedules/2026/autumn_recheck_calendar.csv \
  --as-of 2026-10-07 \
  --output audits/phase2/stage12o/stage12o_due_queue_20261007.csv
```

## 判定ルール

`next_scheduled_date` と `--as-of` を比較する。

- next == as_of: `today_pending`
- next < as_of: `overdue`
- next > as_of: 出力しない

このため、checkpoint日に処理できなかった大会も翌日以降に消えず、overdueとして再照合対象に残る。

## 10/7スナップショット

Stage 12Nの27追跡行から、10/7時点で3追跡行を抽出。

- N-PREF-01: 北海道 / Stage 12I
- N-REG-01: 北海道 / Stage 12J
- N-PREF-13: 福岡 / Stage 12I

ユニーク大会は2大会。

- CMP000013 北海道
- CMP000148 福岡

10/7時点:
- due: 3
- today_pending: 3
- overdue: 0
- next future checkpoint: 10/8

## 取りこぼし対策

10/7分を処理しないまま10/8として実行すると、10/7の3行はoverdueとして残り、10/8予定の京都・和歌山2行がtoday_pendingとして追加される。

したがって10/8時点では5行がdueとなる。

## 役割分離

Stage 12Oは結果を自動確定しない。

- Stage 12N: 将来予定日を保持
- Stage 12O: 今日確認すべき対象を自動抽出
- 実績再照合: 試合結果を確認して、完了試合がある日だけmasterへ確定

この分離により、予定日と実績日の混同を防ぐ。
