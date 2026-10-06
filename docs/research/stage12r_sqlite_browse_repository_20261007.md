# Stage 12R 閲覧read modelのSQLite永続化・repository層

作成日: 2026-10-07

## 目的

Stage 12Qで生成できる3つの閲覧read modelを、GUIが毎回CSV全件を読むのではなくSQLiteから検索できるようにする。

対象:
- 日付別試合一覧
- 大会別結果一覧
- 学校別戦績

Python標準の `sqlite3` のみ使用し、追加依存は導入しない。

## SQLite schema

### browse_seasons

年度単位のロード情報。

- year
- rng_seed
- schema_version
- match_count
- competition_count
- school_count
- loaded_at

`year` を主キーにする。

### matches_by_date

Stage 12Q `DatedMatchRow` を保存。

主キー:

`(year, competition_id, match_id)`

主要index:
- year + match_date
- year + competition_id
- year + team1_id
- year + team2_id

### competition_results

Stage 12Q `CompetitionResultRow` を保存。

主キー:

`(year, competition_id)`

### school_records

Stage 12Q `SchoolRecordRow` を保存。

主キー:

`(year, school_id)`

学校名・都道府県でindexを持つ。

## 年度更新方式

`replace_season_views(year, seed, views)` は年度単位の全置換。

1. 入力read modelを事前検証
2. transaction開始
3. 既存browse_seasonsの対象年度をDELETE
4. FOREIGN KEY ON DELETE CASCADEで3テーブルの年度行を削除
5. 新しい年度metaと3read modelをINSERT
6. commit

入力検証が失敗した場合は既存DBを変更しない。

これにより同じyear/seedで再生成しても重複しない。

## GUI向けquery API

`BrowseRepository` が以下を提供する。

- `season_meta(year)`
- `matches_on_date(year, YYYY-MM-DD)`
- `undated_matches(year)`
- `competition_result(year, competition_id)`
- `competition_matches(year, competition_id)`
- `list_competitions(year)`
- `school_record(year, school_id)`
- `school_matches(year, school_id)`
- `search_school_records(year, text=..., prefecture_code=...)`

### 学校試合履歴

`school_matches` ではGUI表示用にSQLで追加列を生成する。

- opponent_id
- opponent_name
- school_result = W / L / BYE

## season_cli接続

Stage 12Rでは `season_cli` に:

`--sqlite-db`

を追加する。

例:

```bash
python -m phase2_engine.season_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100501 \
  --result-dir out \
  --sqlite-db out/kokosim_browse.sqlite3
```

CSVが不要なら `--result-dir` を省略し、`--sqlite-db` だけ指定してもよい。

## GUIへの接続イメージ

### 日付画面
`matches_on_date(2026, "2026-07-25")`

### 大会画面
`competition_result(2026, competition_id)`
+
`competition_matches(2026, competition_id)`

### 学校画面
`school_record(2026, school_id)`
+
`school_matches(2026, school_id)`

検索画面は `search_school_records` を使用する。

## 複数年度

全テーブルの主キーにyearを含めるため、2026・2027...を同じDBへ保持できる。

将来ゲーム内で年度を進めてもschemaを変えずに追加可能。

## 次工程

Stage 12R後はSQLite repositoryを直接読む最初のGUIを作れる。

優先する最小GUI:
1. 年度選択
2. 日付別試合一覧
3. 大会一覧→大会結果
4. 学校検索→学校戦績

最初はread-onlyとし、シミュレーション実行・設定変更画面とは分離する。
