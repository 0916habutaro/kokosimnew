# School Intake Model 設計 v1

作成日: 2026-10-07

## 目的

学校masterへ固定の戦力値を保存せず、各年度に入学する架空選手の母集団差を通して学校間の戦力差を作る。

処理順は次のとおり。

```
school_id + entry_year + seed
  -> SchoolIntakeProfile
  -> PlayerAbilitySnapshot の生成値を調整
  -> StartingLineup / PitchingStaff
  -> TeamStrengthSnapshot
```

TeamStrengthへ学校補正値を直接加算しない。

## 重要な意味

`school_intake_v1` は実在校の実力評価ではない。

- 実在校名や所在地を使っていても、program_quality_z は架空選手生成用の合成潜在値
- 学校成分はゲーム内の学校評判から作る。初期評判の実績入力と年度更新は `game_definition.md` §3.3・§10を正本とする
- 「この実在校は強い／弱い」という事実を表す値ではない
- 将来実データで校正する場合は別工程とし、根拠・期間・更新ルールを文書化する

## 2階層の入部品質

### program component

学校単位で持続する合成成分。

namespace:

`school_intake_v1:program:{school_id}`

ゲーム中は `AnnualReputation.intake_by_year` に確定した入学年度の学校成分を使う。学校評判の固定指定もこの経路に従い、入学済み年度を変更しない。上記namespaceの乱数は、学校評判のない架空の学校などでの代替値に使う。

### cohort component

入学年度ごとに変化する成分。

namespace:

`school_intake_v1:cohort:{school_id}:{entry_year}`

同じ学校でも2024年度入学と2025年度入学では異なる。

### 合成

現在の合成（学校・年度の重みは既存設定のまま）:

```
intake_quality_z
  = 0.8660254037844386 * program_quality_z
  + 0.5 * cohort_quality_z
  + coach_quality_z
```

学校・年度成分の重みの2乗和は1.0。6-3Aの監督成分は `config/coaches/coach_intake_v1.json` で最大±0.20 zに抑える。

最終値は既存の -3.5〜+3.5 にclipする。能力上限とソフトキャップも変更しない。

### coach component（6-3A）

2027年度以降の新入生だけに適用する。評判50は0、1点あたり0.004 zを加え、±0.20 z以内に制限する。2026年開始時の選手には適用しない。

4月1日の監督人事の直後に `CoachBook.finalize_intake()` で確定する。入学年4月1日の所属を既存イベントから参照し、その人物の `CoachIntakeRating` の確定値を使う。同一人物の評判・補正が変わらない年度は複製しない。現在の監督・現在の評判から過去の補正を再計算せず、名簿の遅延生成と保存再開でも同じ値になる。

学校成分・年度成分と独立した加算であり、学校の評判値は変更しない。`RosterBook._new_state()` が潜在能力の抽選へ渡すのは `program_quality_z` だけで、監督成分を含めない。毎月の成長・能力編集・怪我・復帰では加算し直さない。

## 選手能力への適用

Stage 13B-2の `PlayerAbilityGenerator` はbaselineとして残す。

通常のゲーム生成では `SchoolAwarePlayerAbilityGenerator` を使用し、baseline能力生成後に `intake_quality_z` に応じて能力を調整する。

対象:

- batter scalar abilities
- catcher-only abilities
- pitcher abilities
- 主守備位置のposition aptitude
- pitch quality
- pitch command

pitch count、pitch type、usageはStage 13B-4では変更しない。

これにより「強い学校だから最終TeamStrengthに+10」ではなく、「質の高い入部層が複数学年に存在し、結果としてスタメン・控え・投手陣が強くなる」という経路になる。

## provenance

School-aware能力snapshotには以下を追加する。

- intake_config_id
- intake_config_revision
- intake_config_sha256
- intake_program_quality_z
- intake_cohort_quality_z
- intake_quality_z
- intake_coach_id / intake_coach_reputation / intake_coach_quality_z（生成時の参照情報。保存した名簿の能力は従来どおり選手ごとに保持）

TeamStrengthSnapshotには以下を追加する。

- school_intake_config_id
- school_intake_config_revision
- school_intake_config_sha256

## baseline比較

調整値の妥当性確認では、同じschool_id・seed・選手構成について

- baseline: PlayerAbilityGenerator
- intake: SchoolAwarePlayerAbilityGenerator

を比較する。

見るべきものは主に学校間分散であり、全体平均を大きく押し上げたり押し下げたりしないことを確認する。

## 変更しやすさ

数値は `config/abilities/school_intake_v1.json` に置く。

Python側へ学校ランクや能力補正値を直書きしない。

数値調整はrevisionを上げ、変更前→問題→変更→変更後→判断を `docs/tuning/` に残す。
