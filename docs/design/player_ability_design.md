# 選手能力設計方針 v1

作成日: 2026-10-07

## 目的

ココシミュNewの選手能力は、試合結果・個人成績・年度推移を生み出す内部状態として扱う。
見た目の能力表を作ること自体を目的にしない。

## 基本原則

1. Player本体と能力を分離する。
2. 現在能力は PlayerAbilitySnapshot として時点を持つ。
3. 疲労・調子・怪我は恒久能力に含めない。
4. 打率・防御率・OPS等の成績は能力値として保持しない。
5. 学校打撃力・投手力・守備力は選手能力から算出する。
6. 学校ブランド・名門補正を試合能力へ直接加算しない。
7. バランス値はPythonへ直書きせず config/abilities に置く。
8. 乱数namespaceは能力ごとに分離し、一項目の変更で他能力まで変わりにくくする。
9. 同じseedの完全再現には config_id / revision / canonical_config_sha256 も必要とする。
10. 能力の意味変更と単なる数値調整を区別する。

## データ層

```
Player
  ↓
PlayerAbilitySnapshot
  ↓
Lineup / PitchingStaff
  ↓
TeamStrengthSnapshot
  ↓
MatchSimulation
  ↓
PlayerGameStats
  ↓
SeasonStats / CareerStats
```

### Player

Stage 13Aの恒久的な人物・所属情報。

### PlayerAbilitySnapshot

ある時点の基礎能力。
将来は snapshot_date または season_phase を持たせる。

保存候補:

- player_id
- reference_year
- snapshot_date / phase
- ability_model_version
- config_id
- config_revision
- canonical_config_sha256
- scalar abilities
- position aptitude
- pitch repertoire

### PlayerCondition

能力snapshotとは別にする。

候補:

- fatigue
- condition
- injury_status
- availability

### 成績

能力ではなく試合結果の集積。

- batting_average
- on_base_percentage
- slugging
- home_runs
- ERA
- strikeouts
- walks

などは PlayerGameStats / SeasonStats 側へ置く。

## 能力尺度

通常能力は内部値1〜100。

GUIではS〜Gへ変換できるが、内部計算では数値を使う。

球速だけは実値 km/h を保持する。

守備位置適性は各positionごと1〜100。

## 能力カテゴリ

### 打撃
- contact
- power
- plate_discipline
- strikeout_resistance
- bunt

### 走塁
- speed
- baserunning
- stealing

### 守備
- arm_strength
- fielding
- throwing
- position_aptitude

### 捕手
- catching
- game_calling

### 投手
- velocity_kmh
- control
- stamina
- stuff
- strikeout
- groundball
- composure
- pitch_repertoire

## 現在能力と成長

Stage 13Bでは現在能力を扱う。

成長余地・成長速度・成長タイプは別の DevelopmentProfile とし、Stage 13F付近で導入する。
現在能力に「将来性」を混ぜない。

## 設定変更の扱い

能力の意味・単位・フィールド構造が変わる場合:
- v1 → v2

平均・標準偏差・重みだけ変える場合:
- revision を増やす

いずれの場合も大量生成監査を行う。
