# Stage 13E-3G-36：試験GUIの学校検索・選択試合公開・安全な画面遷移

作業日：2026-10-10

## 目的と到達点

Stage35で既存簡易GUIの大会結果タブから、read-onlyのFMT025予選進行プレビューを`Tkinter.Toplevel`として開けるようにした。今回のStage36は**閲覧操作の安全性と検索性を改善**するもので、正式ゲームGUI・本番大会エンジン・SQLiteの本番テーブルを拡張しない。

改善前は、ヘッドレスの `HiroshimaPreviewGuiModel` で特定試合の状態にアクセスできても、GUIでは「最初のready試合の結果を公開」しかできなかった。また、学校選択は既知校のプルダウンであり、実名の学校を部分一致検索する操作がなかった。Stage36ではこの2点を改善した。

## 実装したGUI操作

- **学校名・学校IDの部分一致検索**：小文字・大文字を区別せず、表示可能になっている学校の文字列から検索する。検索結果が1校なら自動選択し、複数なら該当校の試合・学校戦績・代表校一覧を表示する。0校なら空一覧とし、他校情報を検索結果に混入させない。未実施で`waiting`状態の試合の未来対戦校を検索結果から復元することはない。
- **試合を選んで既登録の結果を公開**：試合一覧から`ready`の1試合を選択すると、Stage32契約とStage33チェックポイントを再検証して、その試合に**既に登録済みの勝者だけ**を公開する。並行して実施可能な一次予選P1・P2では、例えばP2を先に公開できる。一方、必要な一次試合が未実施のR1、結果済み試合、存在しない試合は拒否。新しい勝敗や組み合わせは生成しない。
- **学校↔試合↔代表校の画面遷移**：学校別戦績・代表校の行をダブルクリックすると、その学校の試合一覧を抽出。試合一覧の行をダブルクリックすると「学校1」を絞り込んだ学校別戦績を開く。学校1が未確定の試合では移動しない。フィルタの残骸で不正な校IDが残っても描画前に解除。
- **検索・状態フィルタ解除**：絞り込みを戻しても、既登録結果の段階公開履歴はリセットしない。シナリオ自体を切り替えた場合には既存結果の公開履歴と学校検索条件を消去し、異なる資料の校名を再利用しない。
- **エラー処理**：必要なCSV・JSONが不正／不足している場合には、プレビューを新規表示する前に入力検証を行い、既存GUI側ではエラーダイアログを表示する。失敗を公式ルールの承認として扱わない。

## 画面・ヘッドレス双方の操作

通常GUIの「大会結果」→「予選進行プレビュー（試験・別画面）」から起動し、学校名検索・試合状況選択・学校選択・選択試合の結果表示ができる。

SQLiteを持たずに、Windows上で単独起動する場合：

```bat
examples\run_fmt025_preview_pilot.bat
```

検索の自動検証は、GUIのない環境でも可能：

```bash
python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --headless --data-dir data --scenario fictional --steps 1 --school-query A --status completed
python -m unittest tests.test_stage13e3g36_hiroshima_gui_navigation
```

前者はあくまで架空校Aの既登録済みP1の結果をフィルタする例で、正式大会の試合シミュレーションとは無関係。

## 検証・受入管理

`data/research/2026/hiroshima_gui_stage13e3g36_acceptance_checklist.csv` に、headless PythonモデルおよびUIコールバックの模擬確認 **10件**と、Windows実機で確認する **6件**を別々に登録した。

Windows実機で未実施の項目：

1. 既存SQLite閲覧GUIから試験別窓を起動でき、既存の大会・個人成績には影響しない。
2. 広島西部の既知校名の検索で、対応する行だけ表示される。
3. 学校・代表校・試合一覧のダブルクリックで画面を相互に移動できる。
4. 選択した`ready`試合の既登録結果公開とリセットが期待どおり。
5. ウィンドウ縮小・日本語表示・フォーカス・キーボード操作でレイアウトが崩れない。
6. GUI別窓の開閉・再起動後も既存SQLiteの試合記録や個人成績が変わらない。

CI環境のheadlessテストはこれら実機操作の*論理部分*を検査するが、実際のTkウィンドウの描画・クリック・フォントやDPI表示を検証したことにはならない。Windows実機の画面スクリーンショットを確認できるときに限り手動受入欄を更新する。

`phase2_engine/hiroshima_stage13e3g36.py` はStage35からの回帰、学校検索・独立P2先行・未確定敗者戦拒否と、16受入行の証拠区分を監査する。`tests/test_stage13e3g36_hiroshima_gui_navigation.py` はTkなしで`_render()`/`_search_schools()`/`_choose_selected_school()`/`_choose_selected_berth()`/`_choose_match_first_school()`/`_show_selected_result()`などの**実GUIコールバック**を模擬し、画面の再描画・イベント依存・安全な検索を試験する。

## 出典と正式化に関する禁止事項

2026秋季広島西部の史実25試合・18校・7代表校は、二次結果による結果の段階的再生。2026公式組み合わせの個別試合番号25件、敗者移動矢印32件は未確認。春秋8地区×6経路規則＝48件も未確定のまま。

**検索や試合選択ができるようになっても、実大会の公式組み合わせ自動生成・試合結果のシミュレーション・本番FMT025・任意順位戦は解禁しない。** 既存の学校表示名はまだ正式学校マスターIDと照合されたものではない。次工程で正式GUI化を進めるかどうかも別判断とする。

## 変更ファイル

- `phase2_engine/hiroshima_stage13e3g35_preview_gui_model.py`：既知校の部分一致検索／選択済み`ready`試合のみを公開可能に
- `phase2_engine/hiroshima_stage13e3g35_preview_gui.py`：学校名検索欄、選択試合公開ボタン、双方向の画面遷移、検索解除とheadlessフィルタ
- `phase2_engine/browse_gui_stage13d3.py`：試験別窓の読込失敗時にエラーを表示
- `phase2_engine/hiroshima_stage13e3g36.py`：統合監査
- `tests/test_stage13e3g36_hiroshima_gui_navigation.py`：headless UI模擬テスト
- `tests/test_stage13e3g35_hiroshima_preview_gui_pilot.py`：Stage35の連携assertを新GUI条件に同期
- `data/research/2026/hiroshima_gui_stage13e3g36_acceptance_checklist.csv`：自動／実機を分離した受入台帳
- `data/research/2026/research_pending_queue.csv`：設計・調査キュー引継ぎ

**Stage36完了条件：GUI検索・選択結果公開・安全な往復遷移がヘッドレスで検証され、Windowsの実機表示が未確認であることを正確に残すこと。**
