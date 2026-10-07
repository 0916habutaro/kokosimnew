# Stage 13A 架空選手・学校ロスター基盤

作成日: 2026-10-07

## 位置づけ

Stage 12までで、大会構造・日程・試合結果read model・SQLite・検証GUIまで整備した。

正式ゲームGUIはまだ作り込まず、正式GUIに必要な中核ゲーム機能を先に揃える。

リポジトリ監査の結果、mainには次の実装がまだ存在しない。

- 選手
- 学校ロスター
- 個人成績
- 選手ランキング
- 年度進行時の進級・卒業
- セーブゲーム状態

個人成績・選手能力・年度更新はいずれもplayer_idへ依存するため、Phase 3最初の依存関係として選手ロスター基盤を作る。

## Phase 3の推奨順序

1. Stage 13A: 選手ID・所属・ロスター
2. Stage 13B: 選手能力・チーム能力
3. Stage 13C: 試合内イベント / 個人成績生成
4. Stage 13D: 個人成績read model・ランキング
5. Stage 13E: 日付進行・大会消化
6. Stage 13F: 進級・卒業・新入生
7. Stage 13G: セーブ / ロード
8. 正式ゲームGUI設計

## Stage 13Aの責務

Stage 13Aでは以下だけを扱う。

- player_id
- school_id
- program_id
- 仮表示名
- 学年
- 入学年度
- roster_no
- primary_position
- position_group
- 投打
- roster_status
- generation seed

以下はまだ扱わない。

- ミート/パワー/球速などの能力
- 打順
- 先発投手
- 試合内打席
- 打撃/投手成績
- 成長
- 怪我
- 進級・卒業
- 正式な日本人名

## 20人ロスター

Stage 13Aでは正式大会登録規則そのものではなく、ゲーム内部の最小構造ロスターとして1校20人を採用する。

`roster_status=active_core`

として明示し、将来「部員全体」と「大会登録メンバー」を分離できるようにする。

### 学年構成

- 1年: 5
- 2年: 7
- 3年: 8

合計20。

これは能力・新入生・卒業モデル導入前の構造契約であり、後続Stageで調整可能。

### 守備位置

- P: 5
- C: 2
- 1B: 1
- 2B: 2
- 3B: 2
- SS: 2
- LF: 2
- CF: 2
- RF: 2

position_group:

- pitcher
- catcher
- infielder
- outfielder

## seed再現

学校ごとにnamespaceを分離する。

例:

`player_roster_v1:2026:SCH000001:grades`

`player_roster_v1:2026:SCH000001:positions`

`player_roster_v1:2026:SCH000001:player:1`

同一seed / year / schoolなら同一ロスターになる。

別seedではplayer_id自体を変える。

## player_id

`seed + player_v1 + reference_year + school_id + roster_no`

をSHA-256へ通し、先頭20hexを使用する。

例:

`PLY0123456789ABCDEF0123`

ゲームワールドごとの架空選手を明確に分離する。

## 名前

Stage 13Aでは正式名前辞書をまだ結合しない。

デフォルト:

- 仮選手01
- 仮選手02
- ...

`name_source=placeholder_v1`

を必ず保持する。

`PlayerRosterGenerator(name_provider=...)`

で外部name providerを注入できるため、既存の日本人名データを採用する段階でロスター構造を変更せず差し替えられる。

## 静的CSVを正本にしない理由

3,746校 × 20人 = 74,920人規模になる。

この全量をGit管理の正本CSVとして固定せず、seedからruntime生成する。

必要なときだけCLIでCSVへ出力する。

## CLI

1校:

```bash
python -m game_core.player_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100701 \
  --school-id SCH000001 \
  --output out/players_SCH000001.csv
```

全校:

```bash
python -m game_core.player_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100701 \
  --output out/players_2026.csv
```

全校生成はiterator方式とし、約7.5万人を一度にリストへ保持しない。

## 次工程

Stage 13Bでは、Playerへ能力値を直接詰め込みすぎず、能力snapshotを別モデルとして設計する。

候補:

### 野手
- contact
- power
- plate_discipline
- speed
- defense
- arm

### 投手
- velocity
- control
- stamina
- pitch_quality

その能力から学校単位の打撃力・投手力・守備力を導出し、Stage 12Pのgenerated_v1スコアを能力ベース試合モデルへ置換する。

個人成績はその後に実装する。
