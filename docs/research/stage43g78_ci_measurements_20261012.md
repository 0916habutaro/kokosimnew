# Stage43G-78：GitHub Actionsで実測したv2学校検索性能（小規模fixture）

記録日：2026-10-12

実行元：[Stage43G-78専用GitHub Actions run 38187884233](https://github.com/0916habutaro/kokosimnew/actions/runs/38187884233)

実行コマンド：
```bash
python -m phase2_engine.career_v2_school_search_benchmark --years 4 --games-per-year 40 --repetitions 3
```

## 実際に計測した条件

| 項目 | 実測値 |
|---|---:|
| 架空ゲーム年 | 10000〜10003（4年度） |
| 完全A形式の合成試合 | 160試合（各年40試合） |
| 対象学校IDの該当試合 | 8試合 |
| 検索の繰り返し回数 | 3回 |
| v2原本SQLite | 778,240バイト |
| 架空カレンダーSQLite | 8,192バイト |
| fixture作成・封印 | 0.346秒 |

## 計測結果

| 検証方法 | 中央値 | 最大値 | 3回の実測（ms） |
|---|---:|---:|---|
| `page`：表示ページの原本SHAのみ | 4.989 ms | 5.065 ms | 5.065 / 4.989 / 4.941 |
| `selected_years`：対象年度に保存した全校・全大会の原本SHA | 15.151 ms | 15.215 ms | 15.151 / 15.215 / 15.072 |
| `competition_page`：大会IDを指定したページSHA | 5.004 ms | 5.104 ms | 5.104 / 5.001 / 5.004 |

厳密検証`selected_years`は今回の小規模fixtureではページ検証の約3倍の中央値。これは**この実行環境とデータ形状に限る実測**であり、処理時間をどの環境にも保証せず、100年度まで単純に比例・外挿しない。

## SQLite EXPLAIN QUERY PLAN

- 学校JSON1フィルタ付き`COUNT(*)`：`SEARCH v2_option_a_matches USING INDEX idx_v2_games_day (year>? AND year<?)`
- 学校JSON1フィルタ付き最初の30件：同じ`idx_v2_games_day`の年度範囲検索
- 封印ledger行：`SEARCH v2_option_a_matches USING INDEX sqlite_autoindex_v2_option_a_matches_1 (year=?)`

このプランは**年度条件のインデックスを使っている**が、`team1_id`/`team2_id`はJSON原本内だけにあるため、学校ID自体には専用索引が存在しない。年度内の合成試合をJSON1で抽出するため、対象期間の拡大で負荷増加が想定される。

## 原本不変更の確認

読み取り前後に`fictional_option_a_v2.sqlite3`と`sandbox_calendar_v2.sqlite3`のSHA-256がそれぞれ一致した。fixtureは専用一時領域で新規作成したもの。既存保存ファイルを変更・移行していない。

## 結論と制約

**小規模160試合の完全A形式架空v2検索では、3回の全検証で正常に取得・原本SHAの不変性を確認。** 一方、全国3000校・50年／100年の実プレイセーブについて検索性能と容量を検証したことにはならない。この結果だけで追加索引が必要か不要かを決めず、今後は独立読み取り索引の設計可能性と、段階的なデータ規模の検証を行う。

この結果はGitHub Actionsログの固定fixture条件での数値であり、新たなrunでは数値が変わり得る。
