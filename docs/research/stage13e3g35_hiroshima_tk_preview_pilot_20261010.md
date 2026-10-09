# Stage 13E-3G-35：簡易GUIへのFMT025予選進行プレビュー試験接続

作業日：2026年10月10日

## 成果の位置づけ

Stage34までで、一次予選・敗者復活の **read-only 逐次結果ビュー** を、待機／対戦校確定／結果確定に分けて用意した。Stage35ではこのビューを実際に利用できる **Tkinterの試験ウィンドウ** に接続した。

- 既存の`Stage13D3BrowseApp`大会結果画面へ「**予選進行プレビュー（試験・別画面）**」ボタンを追加。これを押すと独立した`tk.Toplevel`が開く。
- 当該データはまだ本番FMT025の試合生成結果ではないため、SQLiteの`BrowseRepository`や従来の得点確定済み`DatedMatchRow`には書き込まない。
- 通常の「日付別試合」「大会結果」「学校戦績」「個人成績ランキング」は既存のまま保持し、プレビューは**明確に独立した実験機能**とする。

## 試験GUIの表示と操作

`phase2_engine/hiroshima_stage13e3g35_preview_gui.py` が試験ウィンドウと起動エントリポイントを提供する。

| 項目 | UI内容 |
|---|---|
| 閲覧データ | 「架空4校（3試合）」「2026秋季 広島西部（史実25試合）」の**2つだけ**から選択 |
| 次の結果を表示 | `Stage33`に既に登録された勝者を1試合ずつ**公開**。新たな勝敗は計算しない |
| 最初から表示 | チェックポイントを初期状態へ戻し、試合は未実施状態にする |
| 試合状況絞り込み | 全状態／対戦校待ち／対戦校確定／結果確定 |
| 学校絞り込み | その時点で出場校が判明している学校だけを選択 |
| 大会別・試合進行 | 試合ID、状態、フェーズ、2校、得点未収録、勝者、日付・出典 |
| 学校別戦績 | 既に公開した試合の勝敗・現在対戦校が確定している次の試合数・代表状態 |
| 県大会進出確定 | 確定した代表校と、代表権の発生した試合ID |

学校別・代表校一覧の行をダブルクリックすると試合画面をその学校で絞り込める。

### 必須の表示上の区別

- 架空シナリオは実在高校や公式大会の証明ではない。結果日付は全件未定。
- 2026広島秋西は**当年度二次結果から取り込んだ史実25試合**。初期18校→試合25→県大会代表7校を段階公開する。
- 試合の未実施状態にある勝者や未来の対戦学校は非表示。試合日付は完了済みになって初めて「二次結果日付」として表示する。
- Stage25の登録は勝敗が中心のため **全試合得点「－」**、コールド・タイブレーク・球場等も捏造しない。
- 学校名はStage25の**学校名文字列**であり、学校マスターの恒久IDと同一と保証しない。
- **2026公式個別試合番号25件・転送矢印32件は未照合**。Stage30の春秋8季節地区×6＝48件の未解決公式抽選・敗者送り要件も維持。FMT025本体／任意順位戦のlive許可は**常に不可**。

## Windows起動手順

### 既存の簡易GUI内から開く場合

従来どおり閲覧用SQLiteがある場合：

```bat
python -m phase2_engine.browse_gui --db out\kokosim_browse.sqlite3 --data-dir data
```

既存GUIの「大会結果」タブ下部「**予選進行プレビュー（試験・別画面）**」をクリック。既存のSQLiteデータとは独立した2種類の試験データだけが選択できる。現在GUI内で選択している大会と、試験データの大会を混同しないこと。

### SQLiteなしで試験プレビューを単独起動する場合

```bat
examples\run_fmt025_preview_pilot.bat
```

または：

```bash
python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --data-dir data
```

Tkinterが必要。LinuxのGUIなしCIではウィンドウを開かないため、下記のヘッドレス確認を実施する。

### GUIなし確認コマンド

```bash
python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --data-dir data --headless --scenario fictional --steps 2
python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --data-dir data --headless --scenario observed_2026_autumn_west --steps 25
python -m unittest tests.test_stage13e3g35_hiroshima_preview_gui_pilot
```

画面なし起動時も実際にStage32/33/34のread model経由で試合を公開し、完成した表示データをJSONで標準出力へ返す。SQLiteの新規作成・更新をしない。

## 変更ファイル

- `phase2_engine/hiroshima_stage13e3g35_preview_gui_model.py`：GUIと分離した**ヘッドレスの状態・絞込プレゼンター**。入力とチェックポイントを毎回監査する。
- `phase2_engine/hiroshima_stage13e3g35_preview_gui.py`：Tkinterの試験画面、2選択、段階公開・リセット・学校/状態フィルタ、3つの表示タブ。単独GUIとヘッドレス起動対応。
- `phase2_engine/browse_gui_stage13d3.py`：既存簡易GUI大会結果画面に別窓起動ボタンを追加。
- `phase2_engine/hiroshima_stage13e3g35.py`：二例のheadless監査（架空の4状態と史実25試合・18校・7代表の試合公開）。
- `tests/test_stage13e3g35_hiroshima_preview_gui_pilot.py`：大会切替、絞込、勝敗表示の保護、GUI画面構造・旧機能維持、途中保存復元、公式証拠の誤解禁を検出。
- `examples/run_fmt025_preview_pilot.bat`：SQLite不要の単独Windows起動。
- `data/research/2026/research_pending_queue.csv`：研究進捗保存。

## 実機表示確認チェックリスト（未実施部分を混同しない）

GitHub Actionsはheadlessであり、Tkinterウィンドウの**実機スクリーンショット確認はこのCIだけではできない**。Windows GUI環境で以下を別途確認する：

1. 通常GUIの大会結果タブから試験別窓が開き、通常の結果・ランキングを変更しない。
2. 架空4校で開始時はP1/P2が対戦確定、R1が対戦校待ち。試合1→2→3と結果ボタンを押すと3代表が確定。
3. 2026広島西部へ切り替えると史実25試合へ切替。開始は結果未公開、最後に7校進出。二次史実・得点未収録・公式ルール未確定の注記が残る。
4. 学校や状態の絞込、学校一覧から試合一覧へのダブルクリックで意図した行だけ表示する。
5. 何度画面を開閉・結果を公開しても既存SQLiteを変更せず、別窓から本番の大会進行が動かない。

## 何が未完成か

正式ゲームGUI、全都道府県の実大会へのFMT025接続、試合結果の新規生成、SQLite上の進行中大会保存、学校マスターIDとの紐付け、公式2026個別敗者転送規則の確認、年度変更時の普遍的な抽選ルールは**未実装・未証明**。

Stage35で達成したのは、**既存の簡易GUIからread-only実験結果を安全に閲覧する操作をつなぐこと**。正式本体の大会実行の解禁ではない。
