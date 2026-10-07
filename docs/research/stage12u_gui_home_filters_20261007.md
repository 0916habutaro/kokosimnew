# Stage 12U GUIホーム・日本語フィルタ・トーナメント直接遷移

作成日: 2026-10-07

## 目的

Stage 12Tでread-only GUIの基本操作性を整えたため、次の閲覧性改善をまとめて実装する。

- 都道府県コードを都道府県名表示へ変更
- 春 / 夏 / 秋フィルタ
- 大会種別フィルタ
- ホーム画面
- トーナメント表の学校名クリック遷移

実績更新・シミュレーション操作は引き続きGUIから行わない。

## 実装方針

Stage 12Tの `EnhancedBrowseApp` を残し、新規に:

`phase2_engine/browse_gui_stage12u.py`

の `Stage12UBrowseApp` を追加する。

`browse_gui.py` の起動入口だけをStage 12Uへ変更する。

これによりStage 12S / 12Tの画面実装を残したまま、Stage 12Uの追加機能を分離する。

## 都道府県名

GUI内で都道府県名をハードコードしない。

正本:

`data/master/prefectures.csv`

を `BrowseGuiModel` が読み込み、

- 11 → 埼玉県
- 13 → 東京都

のように表示する。

`browse_gui` に `--data-dir` を追加し、デフォルトは `data` とする。

prefectures.csvが取得できない場合だけコード表示へフォールバックする。

## 季節フィルタ

正本値:

- spring
- summer
- autumn

GUI表示:

- 春
- 夏
- 秋

日付別試合画面と大会結果画面の双方に追加する。

## 大会種別フィルタ

2026 competition masterに存在するcompetition_typeを利用する。

- spring_prefectural → 春季県大会
- spring_regional → 春季地区大会
- summer_local_qualifier → 夏地方大会
- national_invitational → 選抜大会
- national_championship → 全国選手権
- autumn_prefectural → 秋季県大会
- autumn_regional → 秋季地区大会
- national_autumn_championship → 秋季全国大会

季節選択時は該当するcompetition_typeだけを候補へ残す。

## 日付別試合

Stage 12T:

- 日付
- 大会
- 都道府県

Stage 12U:

- 日付
- 季節
- 大会種別
- 大会
- 都道府県

SQLite検索では:

- match_date
- season_segment
- competition_type
- competition_id
- prefecture_code

を組み合わせる。

フィルタはすべて任意。

## 大会結果

大会画面に:

- 季節
- 大会種別

フィルタを追加する。

選択条件に合わせて大会combobox自体を絞る。

日付別画面から大会へ遷移する場合は大会フィルタを一度全解除し、対象competition_idを確実に選択する。

## ホーム画面

最初のトップレベルタブとして `ホーム` を追加する。

表示:

- 選択年度
- 試合数
- 大会数
- 学校数
- 春大会数
- 夏大会数
- 秋大会数
- 基準日
- 当日の試合数
- 直前の試合日
- 次の試合日

ボタン:

- 今日 / 次の試合日を開く
- 大会一覧を開く
- 学校検索を開く

todayはGUI実行日のローカル日付を使用する。

## トーナメント表

Stage 12Tではトーナメントカードを描画した。

Stage 12Uでは各カード内の学校名をクリック可能にする。

クリック:

`学校名 → 学校戦績タブ`

勝者は太字表示を維持し、学校名はリンク相当として青系文字で表示する。

マウスオーバー時はhand cursorへ変更する。

## 学校戦績

都道府県フィルタ:

Stage 12T:
- 11
- 13

Stage 12U:
- 埼玉県
- 東京都

学校検索結果の「県」列も都道府県名に変更する。

内部検索値は引き続きprefecture_codeを使用する。

## Repository追加

`BrowseRepository`:

- `list_season_segments(year)`
- `list_competition_types(year, season_segment="")`
- `list_competitions_filtered(...)`
- `matches_for_date_filtered(...)` にseason_segment / competition_typeを追加

Stage 12TのAPIは互換維持する。

## GUI model追加

`BrowseGuiModel`:

- prefectures.csv読込
- `prefecture_label`
- `prefecture_options`
- `season_segment_options`
- `competition_type_options`
- フィルタ付きcompetition_options
- フィルタ付きmatches_for_date_choice
- `home_summary`

## read-only契約

Stage 12Uにも以下は置かない。

- INSERT
- UPDATE
- DELETE
- replace_season_views
- save_season_browse_repository

SQLiteは閲覧専用repositoryとして利用する。

## 次工程

Stage 12U後は、GUIは閲覧用としてかなりまとまった状態になる。

次候補:

1. Windows実機確認
2. ホーム画面の主要大会・注目カード表示
3. GUI表示設定の保存
4. 学校プロフィール情報の追加
5. 本格的な試合シミュレーション / シーズン進行GUI
6. 選手・個人成績read model

秋季実績はStage 12Oのdueキューで後追い可能なため、GUI開発とは分離して継続できる。
