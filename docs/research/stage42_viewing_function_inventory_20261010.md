# Stage 42：閲覧機能の全体インベントリ・設計書化（調査報告）

作成日：2026-10-10  
ブランチ：`codex/stage42-viewing-feature-specification`  
対象：mainのStage13E-3G-41 / PR #127までのコード・文書

## 今回の判断

**追加の正式GUI実装ではなく、GUIに依存しない閲覧機能の全体要求をテキストとして固定する**ことを採用。ゲームの主役は高校野球の試合・大会・成績の閲覧である。従来の簡易GUIで見られる機能だけではなく、試合詳細・大会方式別の画面・学校能力・複数年度の記録も候補として漏れなく台帳化した。

## 調査した実装・資料

| 調査先 | 確認した事項 | 正本と区別 |
|---|---|---|
| `phase2_engine/browse_gui.py`、`browse_gui_stage12u.py` | ホーム、日付別、季節/大会フィルタ、学校・大会閲覧の簡易Tk GUI | 正式GUIではない |
| `phase2_engine/browse_gui_stage13d3.py` | 選手検索・学校ロスター・大会ランキング・学校への遷移 | Tkネイティブ実機目視は別確認 |
| `phase2_engine/browse_gui_model.py` | SQLite検索・年度・大会・学校・選手・ランキングのread model API | APIがあっても専用画面がない場合あり |
| `phase2_engine/browse_repository.py` | SQLiteの年度別保存、学校・大会検索、試合イベント・打撃/投球GameStats読出し | `_initialize_schema_conn`のDDL可能性に留意 |
| `phase2_engine/browse_views.py` | 日付別試合、大会成績、学校戦績の集計構造 | 生成されたスコアと史実二次結果を混同しない |
| `phase2_engine/player_stats_read_model.py` | 打者・投手集計と率指標・規定・ランキング | 長期キャリアID継続は別途確認 |
| `docs/design/player_master_gui_contract.md` | シーズン内の選手同一性、表示項目、SQLite player_master | 年度間同一選手の実装状態を次工程で再調査 |
| `docs/design/team_strength_design.md` | 学校能力は選手能力・起用から導出 | 学校固定能力をUIに捏造しない |
| `phase2_engine/hiroshima_fmt025_preview_browse_model.py`、Stage35〜41 | 架空4校と2026広島秋西のread-only進行・学校ID安全照合 | 本番FMT025ではない |

## 成果物（日本語）

1. `docs/design/viewing_feature_catalog_stage42.csv` — 71機能・13分類、暫定優先度、現状判定、必要データ、調査元。
2. `docs/design/viewing_features.md` — 機能全体仕様、分類・非達成・更新ルール。
3. `docs/design/viewing_screen_navigation.md` — 画面情報構造、年度/大会/学校/選手キーと戻り・誤遷移防止。
4. `docs/design/viewing_data_requirements.md` — 保存・計算・未収録の区分と、史実二次結果/ゲーム生成結果のデータ隔離。
5. `tests/test_stage42_viewing_feature_specification.py` — 71件・状態・参照パス・出典/未実装区別を監査。

## 現状判定と注意書き

| 区分 | 機能件数 |
|---|---:|
| 簡易GUI試作 | 22 |
| 読取モデル/APIはある | 10 |
| 広島隔離プレビュー限定 | 6 |
| 設計資料・契約のみ | 4 |
| 今後の候補 | 29 |
| **合計** | **71** |

この数字は「仕様行数」であり、GUI機能の実装完成率ではない。全機能が実データで検証できる、または全国大会方式が本番で動くという意味ではない。

- 広島秋西の学校名18/18学校マスター照合は完了済み。ただし、公式2026の25個別試合番号・32敗者進行矢印、春秋8地区の公式ルート48件は未確認。
- 本番FMT025および任意順位戦は引き続き保留。研究用の史実二次結果や架空データをゲームの生成結果に合算しない。
- Windows実機のGUI受入10項目はStage41から未実施のまま。今回もCIの文書テストが成功しても描画確認は完了としない。
- 表示優先度P0/P1/P2は**提案であり確定要件ではない**。Stage43のデータ充足調査・ユーザーによる内容の見直しを前提とする。

## 次工程

**Stage43：71項目を実データ・保存スキーマへ照合し、優先度案を見直す。** 特に新規保存が必要な「イニング別得点」「先発・交代」「選手の年度横断ID」「学校能力snapshot表示」「複数年度の歴代大会」などを先に抽出する。Stage44で画面構成・戻り・検索設計を深め、Stage45以降に不足read modelを小さく実装する。

正式GUIの制作開始日はここでは決定しない。
