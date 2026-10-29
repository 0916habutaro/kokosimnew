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

## 出場状態の基盤（本番未接続）

`game_core/match_state.py` の `TeamMatchState` は、DHなしの出場状態を扱う。
今回はこの状態と操作だけを追加し、`MatchSimulator.simulate()` は従来の打順・
登板順を使い続ける。継投後に打順・配置が更新されない既存の問題は、まだ解消していない。

- 初期化は既存の `StartingLineup.batting_order`・`defensive_position` を使用する。
  `primary_position` や能力は参照せず、先発選考・投手起用順を作り直さない
- 登録ID集合は呼出側が渡す。現在の出場者と控えは打順・登録集合・退場集合から
  求める。登板投手IDはPの担当者から取得し、独立した変更可能な項目を持たない
- `BattingOrderSlot` は1〜9の枠と現在の選手を分離する。DHなしでは打順9人と
  守備9人が一致し、各位置・各打順の選手は重複せず、全員が登録されていることを検証する
- `change_positions()` は位置→出場中選手IDの交換・循環、`swap_positions()` は2位置の交換。
  打順と退場集合は変えない
- `substitute()` は控えを退場者の打順枠へ入れる。付随する `defensive_changes` も
  同時に適用できる。退場者は控えへ戻さず、再出場を拒否する
- `change_pitcher()` は出場中の野手なら現投手と位置交換し、控えなら現投手と交代する。
  別の `outgoing_player_id` を指定すれば、その選手を退場させ、元投手をその守備位置へ
  残せる。能力・球数・投手としての登板可否・再登板規則の判断は行わない
- 操作は候補全体を検証してから内部の不変スナップショットを一度だけ置換する。
  失敗時は打順・配置・控え・退場者・履歴のすべてを維持する。公開する集合・枠・
  履歴は不変。登録集合は初期化時に作成し、状態変更時は共有する。
  控え集合は参照時にだけ算出し、変更の検証は9人の配置と退場者を対象にする
- `LineupChange` は成功した変更だけを連番・種類・交代選手・打順枠・位置別の前後IDで保持する。
  無変更操作は履歴を増やさない。全選手の能力コピーや全打席の状態履歴は持たない

**実際の登板投手との照合は別途必要**。`actual_pitcher_id` を省略した初期化と
`validate()` が保証するのはモデル内の整合性だけである。実際の投手が分かっている場合は、
初期化または `validate(actual_pitcher_id=実際の投手ID)` へ渡す。不一致は例外とし、
自動でPだけを書き換えたり、打順の不一致を隠したりしない。

現在は `StartingLineup` のPと `PitchingStaff` の先頭が一致していても、
`MatchSimulator._game_staff()` が残球数を調べ、別の投手を先発に選ぶ。
元投手の残りが0球・60球の場合などに、この相違を検出するテストを置く。
控え投手を入れる状態変更操作は用意するが、今回の本番試合へは適用しない。

**次工程の接続箇所**：

1. `AbilityMatchResolver._competition_team_input()` の大会登録者と、その日の負傷等で
   除外した起用候補を区別して登録集合を渡す。`TeamMatchInput.player_abilities` は
   健康状態で絞られている場合があり、それを常に大会登録全員と見なさない
2. `simulate()` の `_game_staff()` 呼出後に実際の先発を確認し、打順・Pを含む
   開始配置をそろえる。先発確定前の調整と、出場後の選手交代は区別し、
   まだ出場していない選手を不用意に退場扱いにしない
3. 打者は打順枠の進行番号から `player_at_order()` で取得し、登板投手は
   `current_pitcher_id` から取得する。タイブレークの前打者参照も枠を基準にする
4. 球数・打者数・失点による交代判断後、打順・配置を一括更新する。
   新出場者の打撃成績行、守備値、出場経験、怪我、走者責任の接続もそろえる
5. 開始配置と実際の交代履歴を `MatchSimulationResult`・A方式履歴へ接続するのは
   後続PRとする。記録時点の打席番号・回・表裏などをその際に関連付け、
   過去試合の配置を現在能力から再選考しない

今回の状態は試合実行用メモリ内だけを想定し、試合結果・履歴・年度封印・セーブへ
項目を追加しない。未使用の永続化APIや旧セーブ互換処理は作らない。

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
