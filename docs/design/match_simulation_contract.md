# Match Simulation Contract v1

作成日: 2026-10-07

## 目的

Stage 13Bまでに作成した選手能力・学校戦力を、Stage 13C以降の試合シミュレーションへ接続する境界を固定する。

Stage 13C-1では確率モデルそのものは実装しない。先に以下を固定する。

- 試合入力
- 試合結果
- winner ownership
- RNG namespace
- ResultView接続
- config provenance
- 個人成績・イベントとの整合条件

## 入力

`MatchSimulationInput`

- match_id
- competition_id
- reference_year
- generation_seed
- team1
- team2

各チームは `TeamMatchInput` として以下を持つ。

- school_id
- TeamStrengthSnapshot
- PlayerAbilitySnapshot一式

TeamStrengthだけで試合を決めない。

選手イベント生成ではPlayerAbilitySnapshotを使い、学校全体の傾向・選手選択にはTeamStrengthSnapshotを使う。

## team1 / team2

Stage 13C v1では試合内順序を固定する。

- team1 = 表の攻撃
- team2 = 裏の攻撃

これは「ホーム校・ビジター校」という現実上の意味を主張するものではなく、シミュレーション内部の順序契約。

## winner ownership

Stage 12までのTournamentEngineはwinner / loserを先に生成していた。

能力ベース試合では最終的に

```
MatchSimulationInput
  -> MatchSimulator
  -> score
  -> winner / loser
  -> TournamentEngineへ同期
  -> ResultView
```

の順にする。

能力モデルのscoreとTournamentEngineのwinnerが矛盾する状態をResultViewで黙って補正しない。

ResultViewはwinner consistencyを検証し、矛盾時はエラーとする。

## ResultView score source

優先順位:

1. `override`
2. `ability_model_v1`
3. `generated_v1`

実スコア等のoverrideは今後も最優先。

`generated_v1` は移行期間のfallbackとして残す。

## MatchSimulationResult

主なフィールド:

- team1_score / team2_score
- winner_id / loser_id
- last_inning / ending_half
- score_source
- config provenance
- TeamGameStats
- MatchEvent列
- BatterGameStats
- PitcherGameStats

完了試合の同点は許可しない。

延長・タイブレーク・コールドは大会ルールprovider側で決めるため、Stage 13C-1で全国共通値を固定しない。

## Config provenance

結果には以下を保存する。

### match simulation
- match_config_id
- match_config_revision
- match_config_sha256

### event catalog
- event_catalog_id
- event_catalog_revision
- event_catalog_sha256

### game stats
- stats_config_id
- stats_config_revision
- stats_config_sha256

試合生成ロジックを後で調整しても、どの契約・設定で生成された結果か追跡できる。

## RNG isolation

`match_simulation_v1.json` でnamespaceを固定する。

- match: `match_v1:{competition_id}:{reference_year}:{match_id}`
- plate appearance: `plate_appearance_v1:{match_id}:{plate_appearance_no}`
- event: `event_v1:{match_id}:{event_no}`

後続Stageで打席確率ロジックを変更しても、別試合や別イベントへ不要な乱数連鎖を起こしにくくする。

## TeamStrengthの扱い

禁止:

- TeamStrengthの単一値だけで得点を直接生成
- 学校ID由来の得点bonus
- school masterの固定戦力を得点へ加算

Stage 13C-2以降では batting / pitching / defense 等のcomponentと、実際の打者・投手能力を組み合わせる。

## Stage 13C-2への接続

次工程で実装するもの:

1. 打者対投手の打席結果確率
2. 走者・out state
3. inning progression
4. 投手交代
5. 試合終了条件
6. eventから個人成績集計
7. 大量試合監査

Stage 13C-1のcontractを変えずに内部確率だけ調整できる構造を目標とする。
