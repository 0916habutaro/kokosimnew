# ココシミュNew

実際の高校野球に沿って、全国の大会・試合・記録が進んでいくのを**眺める**シミュレーションゲーム。Windows専用・個人用。

- ゲームの目的・仕様・進め方：[`docs/design/game_definition.md`](docs/design/game_definition.md)
- 開発の作業ルール（人・AIエージェント共通）：[`AGENTS.md`](AGENTS.md)

## 今の状態（2026-10-21）

段階0（整理）が終わったところ。ゲームとしてはまだ遊べない。

**できること**

- 2026年度の全国3,746校・全162大会（春・夏・秋、県・地区・全国）の構造、日程、進出のつながり
- 架空の選手20人／校の生成、能力、選手の能力から計算する学校の強さ
- 打席単位の試合シミュレーションと個人成績
- 日付を1日ずつ進めて、その日の試合を処理する（コマンド操作）。セーブスロット・オートセーブ・世代バックアップ
- 試合結果・大会・学校・選手を眺める試作の閲覧画面（Tk）

**まだないもの**（詳しくは `game_definition.md` §2）

- ゲームとしての正式な画面（段階2で作成中。`game_definition.md` §9）
- 成長・怪我、監督、選手名（今は全員「仮選手01」形式）、実在に近い学校の強さ
- タイブレーク・コールド・球数制限など高校野球の規定

## 動かし方（Windows / PowerShell）

Python 3.12 以上。画面には pywebview が必要（`pip install -r requirements.txt`）。リポジトリのフォルダで実行する。

```powershell
# 画面を開く（slot01 のセーブがあれば読み込み、なければ新しく始める。セーブは out\saves）
python -m phase2_engine.screen --slot slot01

# EXE を作る（dist\kokosimnew\kokosimnew.exe。セーブは同じフォルダの saves）
pip install pyinstaller
pyinstaller --noconfirm kokosimnew.spec

# 新しいゲームを作る（セーブ先は out\saves）
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves new slot01 --seed 2026100801 --title "2026年シーズン"

# 1日進める／指定日まで進める
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves next-day slot01
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves advance-to slot01 2026-07-31

# セーブの一覧と状態
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves list
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves status slot01

# 閲覧画面用のデータを作る（シーズン一括シミュレーション）
python -m phase2_engine.season_cli --data-dir data --result-dir out\season_2026 --sqlite-db out\kokosim_browse.sqlite3

# 閲覧画面（上で作ったSQLiteを開く）
python -m phase2_engine.browse_gui --db out\kokosim_browse.sqlite3 --data-dir data
```

ほかのコマンドは `--help` で確認できる。

## 構成

| 場所 | 内容 |
|---|---|
| `data/` | 学校・大会・日程・地区のマスター（出典付きの実在データ） |
| `phase2_engine/` | 大会・シーズン進行・保存・閲覧画面 |
| `game_core/` | 選手・能力・試合シミュレーター・学校の強さ |
| `config/` | 能力・試合モデルの調整値（JSON） |
| `historical_data/`, `historical_results/` | 実在校の過去戦績（史実）と検証 |
| `docs/design/` | 設計の正本 |
| `docs/adr/` | 設計判断の記録 |
| `tests/` | テスト |

## テスト

```powershell
# 1ファイルだけ
python -m unittest discover -s tests -t tests -p "test_stage13e3e1_full_season_save_load.py" -v
# 全件（約20分）
$env:KOKOSIM_SKIP_STAGE43G10_E2E = "1"; python -m unittest discover -s tests -t tests
```

CIは `python-tests.yml`（全テスト、Linux）と `windows-game-acceptance.yml`（ゲーム本体の保存・読込・閲覧画面、Windows）の2本。

## これまでの経緯

工程ごとの記録（Stage 12〜43G）は、整理前の状態とあわせてブランチ `archive/pre-cleanup-20261020` に残してある。主な設計判断は `docs/adr/` を参照。
