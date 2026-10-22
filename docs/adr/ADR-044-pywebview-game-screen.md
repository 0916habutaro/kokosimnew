# ADR-044: 正式な画面は pywebview のウィンドウに HTML/CSS/JavaScript で作る

- 状態: Accepted
- 日付: 2026-10-22
- 関連: game_definition.md §9（段階2）

## 背景

これまでの画面は Tk の閲覧画面と、工程ごとに作った試作の画面（`browse_gui*.py`、`career_*_gui_pilot.py` など）だった。閲覧画面は `season_cli` が別に作る SQLite を読み、遊んでいるセーブとは別のものを見ていた。段階2では、日付を進めながら全国の結果・大会・学校・記録を1つの画面で見られる「遊べる最初の版」を作る。トーナメント表（拡大・縮小、勝ち上がりの線）や得点板のような見た目は、Tk では作りにくい。

## 決定

- pywebview（Windows の WebView2）で独立したウィンドウを開き、画面は HTML/CSS/JavaScript で作る。ゲームの処理（Python）と保存（SQLite・セーブ）は今のまま
- Python 側に「画面に出すデータをまとめて返す層」（`phase2_engine/screen/data.py`）を作る。画面（JavaScript）はこの層からしかデータを読まない。画面の中でゲームの計算をしない
- 画面は遊んでいるセーブの内容（進行中の状態と試合の履歴）を直接表示する。`season_cli` が作る閲覧用 SQLite は使わない
- 正式な画面ができたら、Tk の閲覧画面とそれ以外の試作の画面は削除する
- 追加のパッケージとして pywebview が必要になる（`requirements.txt`）。EXE化（PyInstaller）は段階2の最後に行う

## 帰結

- 画面の見た目は Web の技術で自由に作れる。画面のテストは「データの層」が返す内容を確かめる形にし、ウィンドウを開くテストはしない（CIの Linux ではウィンドウを開けない）
- JavaScript から Python を呼ぶ入口（pywebview の `js_api`）は薄く保ち、中身はデータの層に置く
- 外部のサーバーやネットワークは使わない。画面のファイルはリポジトリ内に置き、ウィンドウに直接読み込む
