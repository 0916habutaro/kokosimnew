# Stage 12Q 日付別・大会別・学校別の閲覧read model

作成日: 2026-10-07

## 目的

Stage 12Pで1試合単位の表示用結果を作れるようになったため、ゲーム画面で実際に閲覧する単位へ集約する。

今回追加する閲覧モデルは3種類。

1. 日付別試合一覧
2. 大会別結果一覧
3. 学校別戦績

GUIはこの3CSVを直接読むか、将来API/DBへ同じ列契約を移植できる。

## 日付別試合一覧

出力:

`season_2026_matches_by_date.csv`

主な列:

- match_date
- date_source
- competition_id / competition_name
- stage / phase / round
- team1 / team2
- score
- winner / loser
- result_text

### 日付の扱い

大会エンジンのMatchには現時点でカード単位の公式日付がない。

そこでStage 12Qでは、`season_calendar.csv` の `game_date_list` を日付候補とし、試合順を崩さずに決定論的に配置する。

この値は公式カード日付ではないため、必ず

`date_source=projected_v1`

とする。

日付が未確定の大会は:

- match_date = 空
- date_source = undated

とする。

不戦勝は実試合ではないため:

- match_date = 空
- date_source = bye

とする。

### 実日付override

`competition_id -> match_id -> YYYY-MM-DD`

のoverrideを受けられる。

override日付は現在の `game_date_list` 内でなければならない。

後から公式カード日程や実績を追加する場合も、同じread modelを維持できる。

## 大会別結果一覧

出力:

`season_2026_competition_results.csv`

主な集計:

- 大会名
- season segment / type / level
- start / end
- scheduled_date_count
- first / last match date
- date_sources
- 総match数
- 実試合数
- bye数
- 参加校数
- 優勝校
- 準優勝校
- 総得点
- 1試合平均総得点
- score_sources

Stage 12Pのscore_sourceも引き継ぐ。

## 学校別戦績

出力:

`season_2026_school_records.csv`

集計項目:

- 学校ID / 学校名 / 都道府県
- 参加大会数
- 大会ID一覧
- games / wins / losses
- win_pct
- runs_for / runs_against
- run_differential
- titles
- runner_up_finishes
- last_game_date

### 不戦勝

不戦勝は実試合ではないため、

- games
- wins
- losses
- runs_for
- runs_against

には加算しない。

ただし大会への登場・参加は保持する。

## season_cli接続

既存:

`python -m phase2_engine.season_cli --data-dir data --year 2026 --seed ... --result-dir out`

で、従来の構造監査出力に加えて3閲覧CSVを生成する。

## Stage 12Pとの役割分離

Stage 12P:
- 1試合単位の表示用score/result

Stage 12Q:
- 日付軸
- 大会軸
- 学校軸

この分離により、後からスコア生成器やGUIを変更しても集計契約を維持しやすい。

## 次工程候補

Stage 12Q後はGUIに接続できる状態になる。

優先候補:

- 日付選択→当日の試合一覧
- 大会選択→トーナメント結果・優勝校
- 学校選択→年度戦績・試合履歴

または、先にSQLiteへread modelを保存するrepository層を作り、GUIをDB参照にする方法も取れる。
