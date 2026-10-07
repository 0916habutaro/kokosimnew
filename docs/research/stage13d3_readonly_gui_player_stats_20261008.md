# Stage 13D-3 read-only GUI 個人成績統合 実装報告

作成日: 2026-10-08

## 実装

新規:

- `phase2_engine/browse_gui_stage13d3.py`

継承:

`Stage13D3BrowseApp(Stage12UBrowseApp)`

Stage 12Uまでの

- ホーム
- 日付別試合
- 大会結果
- 学校戦績

を維持したまま、以下を追加した。

## 選手・ロスター

### 選手検索・詳細

検索:

- 選手名 / player_id
- school_id
- primary_position

表示:

- 選手名
- 学校
- 学年
- 守備位置
- 背番号
- 投打
- 打撃season stats
- 投手season stats

### 学校ロスター

player_masterを正本として20人を表示する。

GameStatsが存在しないbench playerも一覧から消えない。

主な列:

- roster no
- name
- grade
- position
- games
- AB
- H
- HR
- AVG
- OPS
- IP
- ERA
- K

## 個人成績ランキング

1大会を選択し、打撃・投手ランキングを左右paneに表示する。

Stage 13D-1で定義した全ranking metricを選択可能にした。

順位・規定到達・sort directionはPlayerStatsReadModelを利用し、GUI側では再計算しない。

## Navigation

追加:

- 学校戦績 → 学校ロスター
- 学校ロスター → 選手詳細
- 大会結果 → 個人成績ランキング
- 打撃ランキング → 選手詳細
- 投手ランキング → 選手詳細

## Launcher

`python -m phase2_engine.browse_gui`

はStage13D3BrowseAppを起動する。

## Read-only

Stage13D3BrowseApp内に

- INSERT
- UPDATE
- DELETE
- replace系repository method
- save_season_browse_repository

は存在しない。

GUIはBrowseGuiModelのread APIだけを使用する。

## Automated validation

Stage 13D-3専用テスト: 9件。

確認:

- Stage12U継承
- 追加2タブ
- 学校→ロスター→選手
- 大会→ランキング→選手
- player search/read model接続
- 全ranking metric
- 表示formatter
- read-only
- default launcher

full suite:

- Python 3.12
- `Ran 468 tests in 14.656s`
- **OK**

## Manual display validation

GitHub Actions環境にはGUI display serverがないため、実ウィンドウ表示は自動化対象外とした。

`docs/research/stage13d3_gui_manual_checklist_20261008.md`

にローカル実機確認手順を固定した。

したがってStage 13D-3のコード・read model統合はPASS、実機画面確認のみMANUAL_PENDINGとする。

## 判断

Stage 13D-3を採用可能。

正式GUIデザインへ進む前に、ユーザー環境でmanual checklistを実行し、列幅・情報量・導線の改善点を回収できる状態になった。

## 次工程

ゲーム中核機能の優先方針を維持する場合、次はStage 13E-1として

- ゲーム内日付
- その日に開催される大会・試合の消化
- 日付進行
- 未消化/消化済み状態
- ability match結果のseason state反映

のcontractを設計・実装する。

GUI側の微調整はStage 13D-3 manual validation結果に応じて後追いする。
