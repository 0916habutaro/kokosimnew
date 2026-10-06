# Stage 12S SQLite read-only GUI 最小実装

作成日: 2026-10-07

## 目的

Stage 12Rで作成したSQLite repositoryを直接読み、ココシミュNewの最初の閲覧GUIを実装する。

今回のGUIはread-onlyに限定する。

対象機能:

1. 年度選択
2. 日付別試合一覧
3. 大会結果・大会内試合一覧
4. 学校検索・学校戦績・試合履歴

シミュレーション実行、データ修正、設定変更は行わない。

## GUI技術

Python標準のTkinter / ttkを使用する。

追加依存は導入しない。

理由:

- Windows標準Python環境で起動しやすい
- 現段階の最小GUIにWebサーバーは不要
- Streamlit等の追加依存を入れずにread-only画面を確認できる
- Stage 12RのSQLite repositoryをそのまま利用できる

## 起動

まずSQLiteを生成する。

```bash
python -m phase2_engine.season_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100501 \
  --sqlite-db out/kokosim_browse.sqlite3
```

GUI:

```bash
python -m phase2_engine.browse_gui \
  --db out/kokosim_browse.sqlite3
```

Windows用:

`examples/run_browse_gui.bat`

DBが存在しない場合はTkウィンドウを開く前にエラー終了し、生成コマンドを表示する。

## 画面構成

### 共通ヘッダー

- 年度選択
- SQLiteのロード件数表示
  - 試合数
  - 大会数
  - 学校数

年度切替時に3画面を再読込する。

## 日付別試合

日付選択から、その日の試合を一覧表示する。

表示:

- 大会
- ラウンド
- チーム1
- 得点
- チーム2
- 勝者
- date_source

game_date_list未確定の試合は `日付未定` として専用選択肢にまとめる。

Stage 12Qの `projected_v1 / override / undated / bye` をそのまま表示するため、推定日を公式実績と誤認しにくい。

## 大会結果

大会選択:

`大会名 [competition_id]`

概要:

- 大会期間
- 優勝校
- 準優勝校
- 実試合数
- 不戦勝数

試合一覧:

- 日付
- ラウンド
- チーム1
- 得点
- チーム2
- 勝者
- date_source

## 学校戦績

検索条件:

- 学校名または学校ID
- 都道府県コード

検索結果:

- 学校ID
- 学校名
- 都道府県
- 試合数
- 勝
- 敗
- 勝率
- 優勝回数

学校を選択すると以下を表示する。

概要:

- 試合数
- 勝敗
- 勝率
- 得失点
- 優勝回数
- 準優勝回数

試合履歴:

- 日付
- 大会
- ラウンド
- 結果
- 対戦相手
- 得点
- date_source

学校視点の結果は:

- W → ○
- L → ●
- BYE → 不戦勝

へ変換する。

## GUI用モデル分離

`browse_gui_model.py` を追加し、Tkinterからrepositoryへのアクセスを分離する。

GUIモデル:

- available_years
- date_choices
- matches_for_date_choice
- competition_options
- competition_detail
- search_schools
- school_detail
- score_text
- result_symbol

これによりTk画面を起動しなくてもheadlessテストが可能。

## Stage 12R repository拡張

GUIに必要な探索APIとして次を追加する。

- `list_years()`
- `list_match_dates(year, include_undated=False)`

既存の書き込みAPIはGUIから呼ばない。

## read-only契約

`browse_gui.py` には以下を置かない。

- INSERT
- UPDATE
- DELETE
- replace_season_views
- save_season_browse_repository

GUIはStage 12Rの検索メソッドのみ使用する。

## 次工程

Stage 12Sで最小閲覧GUIができるため、次は実機起動・画面確認を行い、以下を優先して改善できる。

- 日付画面の大会/都道府県フィルタ
- 大会画面のトーナメント表表示
- 学校画面から対戦相手・大会への遷移
- ホーム画面/本日の試合
- UI配色・フォント・ウィンドウサイズ調整

その後、シミュレーション進行GUIを別Stageとして追加する。
