# ココシミュNew

実際の高校野球に沿って、全国の大会・試合・記録が進んでいくのを**眺める**シミュレーションゲーム。Windows専用・個人用。

- ゲームの目的・仕様・進め方：[`docs/design/game_definition.md`](docs/design/game_definition.md)
- 開発の作業ルール（人・AIエージェント共通）：[`AGENTS.md`](AGENTS.md)

## 今の状態（2026-10-27）

段階5（勢力図の変動）完了・段階6（監督）着手。段階5は10年間・2シード・270,133試合の検証で完了と判断した。画面から日付を進めて、全国の大会・試合・学校・選手・記録を眺められる。

**できること**

- 2026年度の全国3,746校・全162大会（春・夏・秋、県・地区・全国）の構造、日程、進出のつながり
- 架空の選手20人／校の生成（名前と出身の都道府県つき）、毎年の入学・進級・卒業、毎月の成長、怪我と復帰
- 実在の戦績に基づく初期評判、ゲーム内の大会成績による毎年4月の評判更新、新入生の入部品質への反映、選手の能力から計算する学校の強さ
- 打席単位の試合シミュレーションと個人成績、タイブレーク・コールド・7日間500球の球数制限
- 日付を1日ずつ進めて、その日の試合を処理する（画面・コマンド操作）。セーブスロット・オートセーブ・世代バックアップ
- 正式な画面（pywebview）：今日・大会（トーナメント表）・試合・学校・選手・記録・セーブの管理
- 学校の編集から現在のチーム総合力・評判（自動／数値固定）を指定、選手の詳細から能力・守備適性・球種を編集。変更はそのセーブに保存
- 全国の各学校に架空の監督を1人ずつ生成・保存し、2027年から毎年4月1日に退任・異動・後任就任を更新（6-2）。人物IDと所属変更の履歴を保持し、学校詳細に現在の氏名・年齢・在任年数を表示
- 2027年度以降の新入生は、入学時の監督評判によって入部品質が最大±0.20 z変化（6-3A）。評判50が補正0。学校評判と年度の当たり外れは維持し、在籍選手と潜在能力には加算しない
- 2027年4月の練習分から監督の育成力で月間の練習成長を最大±10%補正（6-3B）。対象月1日の在任者を参照し、試合経験・潜在能力・成長タイプは変更しない。処理済み月を保存して二重成長を防ぐ
- 2027年4月1日以降の試合は、試合日の監督の継投・起用傾向を反映（6-3C）。継投の打者数目安は最大±10%、失点目安は最大±1点。同程度の候補の学年で選考に小さな差を付け、球数制限・怪我・守備適性を維持する。選手能力への直接加算は行わない

**まだないもの**（詳しくは `game_definition.md` §2）

- 監督の詳細画面と異動履歴の閲覧（6-4）

## 動かし方（Windows / PowerShell）

Python 3.12 以上。画面には pywebview が必要（`pip install -r requirements.txt`）。リポジトリのフォルダで実行する。

```powershell
# 画面を開く（セーブの画面で、続きから遊ぶセーブを選ぶか新しく始める）
python -m phase2_engine.screen
# slot01 を直接開く（なければ新しく始める）
python -m phase2_engine.screen --slot slot01

# 新しいゲームを作る（セーブ先は out\saves）
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves new slot01 --seed 2026100801 --title "2026年シーズン"

# 1日進める／指定日まで進める
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves next-day slot01
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves advance-to slot01 2026-07-31

# セーブの一覧と状態
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves list
python -m phase2_engine.live_game_cli --data-dir data --save-root out\saves status slot01
```

ほかのコマンドは `--help` で確認できる。

### EXE を作って遊ぶ（Windows）

**作り方**（Python 3.12 以上が入っていること）

1. リポジトリのフォルダ（例：`E:\14.koko\kokosim_github`）で `build_exe.bat` をダブルクリックする（または PowerShell で `.\build_exe.bat`）
2. 必要なパッケージ（pywebview・PyInstaller）を入れてから EXE を作る。数分かかり、終わると「できました」と出て止まるので、何かキーを押して閉じる
3. できるのは `dist\kokosimnew\kokosimnew.exe`。`dist\kokosimnew` フォルダごとなら好きな場所に移してよい（中の `_internal` フォルダも必要）

**起動のしかた**

1. `dist\kokosimnew\kokosimnew.exe` をダブルクリックする
2. 最初はセーブの画面が開く。「新しく始める…」（スロット名・シードは空なら自動）か、前のセーブの「読み込む」を押す
3. 上の「1日進める」「まとめて進める…」で日付を進める。セーブは日付を進めるたびに自動で行われる

**作り直すとき**（main を取り込んだあとなど）：EXE を閉じてから `build_exe.bat` をもう一度実行する。セーブは EXE とは別の場所にあるので残る。

**セーブの場所**：`E:\14.koko\kokosim_github\saves`。場所は `config\screen\screen_v1.json` の `save_root` で変えられる（設定は EXE の中に入るので、変えたら EXE を作り直す）。E ドライブがないときは `%LOCALAPPDATA%\KokosimNew\saves`。

**うまく動かないとき**：セーブのフォルダの `kokosimnew.log` を見る。画面には WebView2 ランタイム（Windows 10/11 には通常入っている）が必要。

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
# 全件（約1時間以上）
$env:KOKOSIM_SKIP_STAGE43G10_E2E = "1"; python -m unittest discover -s tests -t tests
```

CIは `python-tests.yml`（全テスト、Linux）と `windows-game-acceptance.yml`（ゲーム本体の保存・読込・閲覧画面、Windows）の2本。

## これまでの経緯

工程ごとの記録（Stage 12〜43G）は、整理前の状態とあわせてブランチ `archive/pre-cleanup-20261020` に残してある。主な設計判断は `docs/adr/` を参照。
