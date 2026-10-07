# TeamStrengthSnapshot 設計

## 目的

学校の固定能力値を学校masterへ保存せず、当該年度の選手能力・スタメン・投手陣から学校戦力を再計算できるようにする。

```
PlayerAbilitySnapshot
  -> StartingLineup
  -> PitchingStaff
  -> TeamStrengthSnapshot
```

TeamStrengthSnapshotは年度・seed・configに依存するスナップショットであり、学校そのものの恒久属性ではない。

## StartingLineup

9守備位置を1人ずつ選ぶ。

- P
- C
- 1B
- 2B
- 3B
- SS
- LF
- CF
- RF

Stage 13Aの構造ロスターでは各守備位置の本職候補が必ず存在するため、Stage 13B-3では本職候補内から選ぶ。

- P: pitcher quality最大
- C: batting + catcher defense
- その他: batting + defense + running

数値重みは `team_strength_v1.json` の `selection` に置く。

打順は選出9人を `batting_order_weights` で並べる。同点はplayer_idで決定し、seed再現性を壊さない。

## PitchingStaff

primary_position=Pの全選手をpitcher quality順に並べる。

- 1位: ace
- 2位: second
- 3位: third
- 4位以降: depth

pitcher qualityは以下を合成する。

- velocity_component
- control
- stuff
- strikeout
- groundball
- stamina
- composure

球速100〜165km/hは1〜100へ線形変換してから合成する。

StartingLineupのPはPitchingStaffのaceと一致させる。

## TeamStrengthSnapshot

出力はすべて1〜100。

- batting_strength
- contact_strength
- power_strength
- discipline_strength
- running_strength
- defense_strength
- ace_strength
- pitching_depth_strength
- bullpen_strength
- pitching_strength

### 打撃

スタメン9人のcontact / power / plate_discipline / strikeout_resistance / speedと、非スタメン上位3人のbench_depthを合成する。

### 走塁

スタメン9人のspeed / baserunning / stealingを重み付き平均する。

### 守備

投手を除く8守備位置を対象とする。守備位置ごとにfielding / throwing / arm_strength / position_aptitudeを合成し、守備位置重要度で学校値へ集約する。

捕手はcatching / game_callingを含む専用式を使う。

### 投手

- ace_strength: 1番手
- pitching_depth_strength: 2番手以降のstaff weightを再正規化
- bullpen_strength: 3番手以降の平均
- pitching_strength: ace / second / third / remaining_depthの重み付き合成

## provenance

TeamStrengthSnapshotには以下を保持する。

- team_config_id
- team_config_revision
- team_config_sha256
- player_generation_sha256
- generation_seed
- school_intake_config_id
- school_intake_config_revision
- school_intake_config_sha256

これにより後日configを調整しても、過去スナップショットがどの設定から生成されたか判定できる。

## Stage 12Pとの接続方針

Stage 12Pの `generated_v1` は当面残す。

次の能力ベース試合モデルでは、ResultView自体は変更せずscore sourceを差し替える。

```
TournamentEngine winner/loser
  -> ability match simulator
  -> team1_score / team2_score
  -> ResultViewRow
```

移行時は `score_source=ability_model_v1` を追加し、実スコアoverrideは最優先のまま維持する。

最終的にはwinner/loserも能力ベース試合シミュレータが決めるが、Stage 13B-3では接続契約のみ固定する。


## Stage 13B-4 source contract

通常のTeamStrength生成では `SchoolAwarePlayerAbilityGenerator` の出力を使用する。

baselineとschool-awareのPlayerAbilitySnapshotを同一TeamStrength入力へ混在させることは禁止し、validatorで拒否する。

学校差は選手能力を通して形成されるため、TeamStrength集約式へ `school_bonus` のような直接補正は追加しない。
