# Stage 13D-3 read-only GUI player/stats integration

作成日: 2026-10-08

## 目的

Stage 13D-2で整備したplayer master / 個人成績read modelを、既存のread-only Tkinter GUIへ接続する。

正式ゲームGUIのデザイン確定はまだ行わず、read model・画面遷移・情報量が実用に耐えるかを探索GUIで確認する。

## 継承方針

新規:

`phase2_engine/browse_gui_stage13d3.py`

`Stage13D3BrowseApp(Stage12UBrowseApp)`

Stage 12Uまでの

- ホーム
- 日付別試合
- 大会結果
- 学校戦績

を維持し、新規に

- 選手・ロスター
- 個人成績ランキング

を追加する。

既存GUIファイルへ大規模な直接変更を入れない。

## 選手・ロスター

内部Notebook:

### 選手検索・詳細

検索条件:

- 選手名 / player_id
- school_id
- primary_position

検索結果:

- 選手名
- 学校
- 学年
- 守備位置
- 打
- 投
- 背番号
- player_id

選択した選手について

- profile
- season batting
- season pitching

を表示する。

### 学校ロスター

school_idをキーとして20人ロスターを表示。

表示:

- 背番号
- 選手名
- 学年
- 守備位置
- 試合
- AB
- H
- HR
- AVG
- OPS
- IP
- ERA
- K

GameStatsがないbench playerもplayer masterから表示する。

## 個人成績ランキング

大会を1つ選択し、打撃・投手rankingを左右2paneで表示する。

打撃metric:

- OPS
- AVG
- OBP
- SLG
- H
- HR
- RBI
- R
- BB
- SB

投手metric:

- ERA
- WHIP
- K
- K/9
- BB/9
- K/BB
- K-BB%

規定到達判定・sort direction・tie rankingはStage 13D-1 PlayerStatsReadModelを正本とする。

GUI側で順位ロジックを再実装しない。

## 画面遷移

### 学校 → ロスター

学校戦績で学校を選択し
「選択校のロスター・個人成績」
を押す。

### ロスター → 選手

学校ロスター行をダブルクリック。

### 大会 → ランキング

大会結果で大会を選択し
「この大会の個人成績ランキング」
を押す。

### ランキング → 選手

打撃または投手ランキング行をダブルクリック。

## Read-only

Stage13D3BrowseAppは以下を呼ばない。

- INSERT
- UPDATE
- DELETE
- replace_season_views
- replace_season_player_master
- replace_season_match_results
- save_season_browse_repository

すべてBrowseGuiModelのread API経由とする。

## 正式GUIとの関係

Stage 13D-3は情報設計の検証用GUI。

ここで確認する内容:

- 表示情報の過不足
- 学校→選手導線
- 大会→ランキング導線
- ロスター表の列数
- 選手詳細に必要な項目
- 大会ランキングのmetric選択

これらが固まってから正式GUIのデザインへ反映する。
