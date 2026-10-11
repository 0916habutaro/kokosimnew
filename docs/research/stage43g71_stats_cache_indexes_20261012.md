# Stage 43G-71：旧A方式・v2派生成績キャッシュの索引・実容量監査

作成日：2026-10-12

## 実装の位置付け

Stage43G-70ではv2試合原本について、PRIMARY KEYと全列が一致する重複インデックスを新規作成しないようにした。今回も元のA方式・v2試合や学校ロスターは変更しないまま、**派生成績キャッシュ専用SQLite**で重複索引の有無を調べる。

旧A方式の player_year_stat_cache には PRIMARY KEY(school_id,year,player_id) があり、SQLiteは同じ列の一意B-treeを自動生成する。既存スキーマの idx_cached_school_year は、これと列順まで一致する重複索引だった。

一方、旧A方式の idx_cached_player_year(player_id,year) およびv2方式の idx_v2_stat_player_year(player_id,year) は、学校主キーとは列順が異なり、**選手単位の長期閲覧に必要**なので維持する。

## 今回の変更

1. 新規の旧A派生成績キャッシュでだけ、完全重複の idx_cached_school_year を追加作成しない。
2. 旧A派生成績の学校年度・選手年度SQLが、それぞれ主キー／選手先頭インデックスを使用することを EXPLAIN QUERY PLAN で確認する。
3. **既存セーブのSQLiteは一切更新しない。** 以前作られた重複索引があっても、DROP INDEX・VACUUM・テーブル再作成はせず読み取り互換性を維持する。将来新たな年次の派生成績を同じ旧ファイルにmaterializeしても旧索引は残す。
4. 新しい read-only 監査API phase2_engine/career_stats_cache_btree_audit.py から、旧A・v2の両成績キャッシュを個別・同時に分析できるようにする。
5. SQLiteの dbstat が利用可能な場合は、各索引の実際のB-tree割当ページを計測。非対応なら容量値は未取得として示す。**過去ファイルの旧索引が占めるページが、そのまま削除時のディスク節約量だとは主張しない。**

## 実行例

```bash
python -m phase2_engine.career_stats_cache_btree_audit \
  --legacy-cache out/saves/EXAMPLE/derived_player_stats.sqlite3 \
  --v2-cache out/saves/EXAMPLE/fictional_v2_player_stat_cache.sqlite3 \
  --output-json build/reports/stage43g71_cache_indexes.json
```

どちらか一方の既存ファイルだけを指定しても動作する。両ファイルの同一パス指定、存在しないファイル、symlink参照は拒否する。元SQLiteを mode=ro + query_only=ON で読み、監査前後のSHA-256を照合する。

## 境界と検証内容

監査APIが保証するのは**SQLite索引の構造、選択された検索計画、実ファイル容量、元SQLite非書込**のみ。元試合SHA・選手成績の真偽や生涯合計の同定を保証する機能ではない。必要に応じStage43G-67/68で原本と派生cacheの深度照合を行う。

新規8テストは、旧A形式で実際に封印済み2026・2027の2年度分の選手成績キャッシュを生成して検査し、同じJSON行に旧重複索引を付けたコピーのB-treeを比較する。また、既存旧方式の索引をそのまま残して再materialize可能であること、v2専用cacheの選手先頭索引を維持したまま原本と一致した成績を閲覧可能であること、欠損索引・入力ファイル重複を検出し元のDBが変わらないことを確認する。

回帰はStage43G-15/29/70、さらにPython全unittestと関東8都県17校E2Eを確認してからmainへマージする。

## 今後

物理SQLiteファイル容量の直接削減を目指す場合、**実保存と同じレコード数・同じ検索パターンの環境で新旧を比較**し、B-treeページ・ファイルサイズ・検索レイテンシを分けて報告する。既存セーブの索引削減はバックアップ・ロールバック仕様が別途必要。正式GUIの長期閲覧や全国3,000校×100年の連続ゲーム進行を完了した工程ではない。
