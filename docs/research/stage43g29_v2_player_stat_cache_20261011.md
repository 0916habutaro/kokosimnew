# Stage 43G-29：封印v2年度の個人成績を独立・不変キャッシュへ保存

作成日：2026-10-11

前工程 Stage 43G-28 PR #169 はPython全unittest・関東17校E2E・専用10テストの成功後、mainにマージ済み（`660d8242e1693d3ffd7aebe61144a9d504079054`）。

## 機能範囲と原本

- 新規 `phase2_engine/career_v2_player_stat_cache.py` が、**封印済み**架空v2年度の保存済みA方式box scoreから、G-28の年度ロスター／恒久選手ID検証を通過した個人成績を年度・学校・選手ID単位に集計する。
- 格納先は新しい専用DB `fictional_v2_player_stat_cache.sqlite3` のみ。旧`historical_matches.sqlite3`、旧`career_player_stats_cache.sqlite3`、`fictional_option_a_v2.sqlite3`、`sandbox_calendar_v2.sqlite3`、`career_rosters.sqlite3`は**原本として読み取り専用**で扱い、旧実績と自動合算しない。
- `CareerV2PlayerStatCache(view, cache_path).materialize(year, school_id)` で保存。結果が全件同一なら再保存は `inserted=False` とする。変更されたキャッシュ・カバレッジ・元台帳は拒否。
- `read_year(year, school_id, verify_source=False)` は高速モード。年度封印・台帳SHAメタデータ、該当校＋対戦校の全年度ロスター・各恒久選手identity、キャッシュの全行SHA・カバレッジ集計・fact SHAを検証する。DBは `mode=ro` で開き、作成・更新しない。
- `read_year(..., verify_source=True)` は全試合原本SHAを再検証する監査モード。G-28の全原本照合・個人成績集計を再実行し、保存済みキャッシュと完全一致するか比較する。

## 設計上の線引き

1. 未封印年度をキャッシュすることは禁止。G-28で架空合成の全v2試合・選手所属を検証した年度だけを許可。
2. 選手IDは恒久IDのみ。名前・背番号では照合しない。複数年度の通算、卒業後のロスター帰属、連年遷移を推測しない。
3. 「fast read」は元の各試合の全SHAを毎回検証するものではない。試合原本自体の改変に対する強い検出は `verify_source=True` で保証する。キャッシュ独自のSHA、全件行数、年度原本の**封印メタデータ**の検証はfastでも常に実施。
4. 参照元の学校・対戦校の年度ロスターについては、保存済みスナップショットと恒久identity台帳双方を再検証する。
5. `v2_school_year_stat_cache` と `v2_player_year_stat_cache` を別テーブルで持ち、年度・学校・選手IDの複合キーを使用。既存歴代ランキング・GUI・旧通算統計には今回接続しない。
6. 本処理は、2026大会の日付を10000年へ再利用するものではない。入力試合は合成架空試合であり、実大会の10000年経過・全学校大会進行を実行したという意味ではない。

## 検証テスト

`tests/test_stage43g29_v2_player_stat_cache.py` を追加し、以下を実証する。

- 10000年度、2校の20人ロスターと2合成試合を用いた学校別キャッシュ生成、打率等の算出、冪等再投入。
- 年度封印前のmaterialize拒否、既存キャッシュなしの読み取りでDBを自動作成しない。
- 未生成学校の閲覧拒否、キャッシュ1行改変・削除・SHA不一致の検知。
- 元v2封印台帳、恒久選手identity、試合原本SHAの改変の検知。
- fast readとdeep source auditの保証範囲の違い（実際の試合原本SHA改変はdeepで検出）。
- 旧原本・カレンダー・ロスターのファイルSHA不変、旧実績キャッシュを作成・変更しない。

CI: `.github/workflows/career-v2-player-stat-cache.yml`。Python全unittest・関東17校E2Eの成功もマージ条件。

## 残工程

- 旧歴代成績キャッシュとv2側の統合・移行、連年の大会進行・ロスター入学卒業、実際の学校別・大会別記録のGUI統合は未実装。
- 実用上の無制限年数についてはv2の64bit年度キー上限、長期データの分割・バックアップ・復旧と全国3000校規模の性能監査が必要。
- 次工程候補：参照元の統合可否判定ゲート、v2独立キャッシュの部分再生成・検証可能バックアップ、100年模擬継続時の負荷測定。
