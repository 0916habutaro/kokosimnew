# Match Simulator v1 設計

作成日: 2026-10-07

## 目的

Stage 13C-1で固定したMatchSimulation contractを実際に完走する最小能力ベース試合エンジンを実装する。

Stage 13C-2の対象は「試合結果だけ」ではない。

```
PlayerAbility / TeamStrength
  -> plate appearance event
  -> base / out state
  -> inning progression
  -> MatchEvent
  -> Batter / Pitcher / TeamGameStats
  -> score / winner
```

を一貫して生成する。

## 正本

- 実装: `game_core/match_simulator.py`
- 調整値: `config/match/match_simulation_v1.json`
- event定義: `config/match/event_catalog_v1.json`
- stats契約: `config/match/game_stats_contract_v1.json`

アルゴリズムはPythonへ、確率・閾値・進塁係数はJSONへ置く。

## MatchSimulator

入力:

`MatchSimulationInput`

出力:

`MatchSimulationResult`

出力前に必ずStage 13C-1の `validate_match_simulation_result()` を通す。

したがって、得点だけ生成できても

- event runs
- batter runs / hits
- pitcher runs / hits allowed
- PA / BF

が一致しない試合は完成扱いにしない。

## 打順

StartingLineupの `batting_order` を1〜9番として使う。

打順はイニングを跨いで継続する。

v1では代打・守備交代を行わない。

投手交代後も打順側の先発投手player_idは置換しない。これはv1の簡略化であり、正式な選手交代モデル導入時に拡張する。

## 投手運用

PitchingStaffのorderを使用する。

- ace
- second
- third
- depth...

の順で使用する。

交代判定は

- batters faced
- stamina
- runs allowed
- 次投手の有無

で行う。

v1では一度降板した投手の再登板はない。

## 打席eventモデル

通常のevent候補:

- strikeout
- walk
- hit_by_pitch
- single
- double
- triple
- home_run
- reached_on_error
- fielder_choice
- field_out

situational event:

- sacrifice_bunt
- sacrifice_fly

### 基本方針

base probabilityだけで抽選しない。

打者側:

- contact
- power
- plate_discipline
- strikeout_resistance
- speed
- baserunning
- bunt

投手側:

- stuff
- control
- strikeout
- groundball
- pitch repertoire quality

守備側:

- defense_strength

を使ってevent weightを変化させる。

TeamStrengthの総合値を「+n点」のように直接scoreへ加算しない。

## pitch repertoire

投手のpitch qualityは各球種qualityをusageで加重した値を使う。

球種ごとの打者相性はv1では扱わない。

## base state

塁は

`[first, second, third]`

としてrunnerのplayer_idを保持する。

runner identityを保持するため、得点時にBatterGameStats.runsへ正しいplayer_idを加算できる。

## 進塁

single / double / errorの追加進塁は

- runner baserunning
- runner speed
- opponent defense_strength

で確率変化させる。

triple / home runは決定的進塁。

walk / HBPはforceのみ。

fielder choiceはv1では1out＋lead runner除去の簡略モデル。

## sacrifice

### bunt

以下の場合のみ候補。

- 0または1out
- 一塁または二塁に走者
- 三塁走者なし
- 点差が設定範囲内
- batter.buntが最低値以上

### sacrifice fly

field_out候補から

- 三塁走者あり
- 2out未満

の場合に一定確率で変換する。

## inning / game end

通常9回。

- team1 = 表
- team2 = 裏
- 裏側リード時の9回裏省略
- 9回裏以降の勝ち越しでwalk-off
- 同点なら延長継続

大会固有の

- コールド
- タイブレーク
- 特別延長規則

はStage 13C-2 v1の共通モデルへ固定しない。

安全上 `hard_max_innings` を設け、そこまで同点ならエラーとして監査で検出する。

## RNG

1打席ごとに独立namespaceを使う。

event type抽選:

`plate_appearance_v1:{match_id}:{plate_appearance_no}`

進塁等:

`event_v1:{match_id}:{event_no}`

同じseed / match_idなら完全再現。

match_idが変われば同じチームでも別試合になる。

## pitcher earned runs

`_RunnerResponsibilityTracker` の走者責任情報から `runs_allowed` を責任投手へ
加算する。投手交代そのものでは責任を変えない。野手選択では9.16(g)に従い、
前任投手の走者をアウトにしても責任枠を残す。代替打者より前の走者が先に
得点する場合も前任投手の残した数を優先する。同時得点時は可能な限り現在の
対応を保ち、失策・タイブレーク由来の非自責情報も引き継ぐ。

`_EarnedRunTracker` は半イニングについて、チーム用と投手ごとの無失策の塁・
アウト・得点を別に再構成する。救援投手の再構成は登板時の実際の塁とアウト数
から始め、登板前の失策によるアウト機会を引き継がない（9.16(i)）。退いた投手の
再構成も回の終わりまで続け、交代後の失策によるアウト機会を反映する。
失策で押し出された走者などは、後続の安打で無失策でも得点できれば自責点へ
戻るため、`earned_runs` は半イニング終了時（サヨナラ・コールドを含む）に確定する。
打順が一巡しても走者を取り違えないよう、再構成では選手IDと出塁打席を合わせて使う。

タイブレーク配置走者・失策出塁走者とその非自責の代替走者は自責点に含めない。
各投手で `0 <= earned_runs <= runs_allowed`、投手別失点合計と相手得点を検証する。
チーム自責点と投手個人自責点合計の一致は要求しない。チーム自責点は内部検証用で、
現在の試合結果スキーマには追加しない。保存済みの試合結果は再計算しない。

交代判断の「失点」は従来どおり登板中に入った得点数を別に保持して参照する。
公式記録の責任帰属を直しても打席抽選・進塁乱数・打順・投手起用・試合イベント・
打撃成績・勝敗・得点板を変えない。保存形式と試合確率の設定も変更しない。

**現行イベントでの再構成の限界**：`reached_on_error` は打者のアウト機会を1つ
逃したものとして扱い、そのプレイによる進塁を無失策の塁へ加えない。安打では
無失策の走者が実際と同じ塁にいる場合に観測された進塁を使い、塁が異なる場合は
安打の種類による最小進塁を使う（疑いは投手に有利に扱う）。犠打時に仮想三塁に
残る走者は保留し、実際にないスクイズを仮定しない。
打者のアウト機会と走者のアウト逸失の区別、安打に付随する失策、捕逸、
ファウルフライ落球、併殺逸失、打席途中の継投などは現在のイベントに情報がない。
厳密に扱うには失策の対象・失策なしのアウトと進塁・ボールカウント等を追加する必要がある。
本処理がすべての実際の公式記録と一致するとは扱わない。

根拠：[公認野球規則9.16](https://npb.jp/scoring/officialrule_900.pdf)、
[NPB記録員コラム](https://npb.jp/news/detail/20200911_01.html)。

## status

`design_default_not_tuned`

初期確率はエンジンを成立させる設計値。

実在高校野球へ校正済みとは扱わない。

大量試合監査で

- 得点分布
- event率
- 戦力差と勝率
- team1/team2 bias
- 延長率
- 投手使用数

を確認し、revisionを上げて調整する。
