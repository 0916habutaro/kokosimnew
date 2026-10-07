# Tournament Ability Integration

作成日: 2026-10-07

## 目的

Stage 13C-2で完成した能力ベースMatchSimulatorを、既存のPhase 2大会ブラケットへ接続する。

Stage 13C-3では大会方式の構造を作り直さない。

Phase 2が

- entrant
- seed
- draw
- round
- next match
- champion / ranking

を管理し、Stage 13が非bye MAIN試合の

- score
- winner / loser
- MatchEvent
- GameStats

を管理する。

## 接続経路

```
AnnualCompetitionInput
  -> TournamentEngine
  -> MAIN bracket
  -> AbilityMainMatchResolver
  -> TeamMatchInput cache
  -> MatchSimulator
  -> MatchResolution
  -> next round
  -> CompetitionRun.match_simulation_results
  -> ResultView / persistence
```

## Phase 2 / Stage 13 境界

Phase 2からgame_coreを直接importしない。

Phase 2側は汎用の `MatchResolution` だけを理解する。

`MatchResolution`:

- winner_id
- loser_id
- team1_score
- team2_score
- score_source
- detail

Stage 13側の `AbilityMainMatchResolver` が `MatchSimulationResult` を `MatchResolution` へ変換する。

これにより大会エンジンは能力モデルの内部実装へ依存しない。

## TournamentEngine

constructor:

```
TournamentEngine(repo, main_match_resolver=...)
```

resolver未指定時は従来のrandom winner resolverを使用する。

したがってStage 12の既存呼び出しは変更不要。

## MAINのみをStage 13C-3対象にする理由

既存の前段処理には

- seed event
- branch qualifier
- preliminary qualifier
- league
- repechage
- gate

など多数のformat modelが存在する。

これらすべてを同時に能力モデルへ変更すると、大会構造の回帰と試合モデルの回帰を切り分けにくい。

Stage 13C-3では正式なMAIN本戦のみ能力モデルへ移行し、前段は従来resolverを維持する。

後続Stageで同じ `MatchResolution` 契約を前段へ広げられる。

## AbilityMainMatchResolver

`game_core/tournament_bridge.py`

school_idから以下を生成する。

```
school_id
 -> PlayerRosterGenerator
 -> SchoolAwarePlayerAbilityGenerator
 -> TeamStrengthGenerator
 -> TeamMatchInput
```

同一

- reference_year
- generation_seed
- school_id

のTeamMatchInputは大会中cacheする。

同じ学校が複数試合へ進んでも選手能力・TeamStrengthを再生成しない。

## Match progression

MAIN bracketは各非bye matchでresolverを呼ぶ。

能力resolverが返したwinnerだけを次ラウンドへ送る。

scoreから別途winnerを引き直さない。

`MatchResolution` validatorで

- participant
- winner / loser
- score型
- non-negative
- tie禁止
- score winner一致

を検証する。

## Annual winner override

`AnnualCompetitionInput.main_match_winner_overrides` は従来通りmatch resolverより優先する。

annual override対象matchは能力シミュレーションを実行しない。

これは実績再現等の既存機能を壊さないため。

winnerのみのannual overrideには実scoreが含まれないため、ResultViewのscoreは別途score overrideがない限り既存fallbackを使用する。

## CompetitionRun

新規:

`match_simulation_results: Dict[str, Dict[str, Any]]`

能力シミュレーションを行った各matchの `MatchSimulationResult.to_dict()` を保持する。

summary JSONへもそのまま保存される。

## ResultView

従来は呼び出し側が

`ability_scores={match_id: [score1, score2]}`

を明示的に渡す必要があった。

Stage 13C-3以降は `CompetitionRun.match_simulation_results` を自動読込する。

優先順位は維持する。

1. score override
2. embedded / explicit ability_model_v1
3. generated_v1

embedded resultについて

- team1
- team2
- winner
- loser

がTournament Matchと一致することも検証する。

## Persistence

`save_competition_run()` はability resultが存在する場合、従来3ファイルに加えて以下を出力する。

- `*_ability_matches.csv`
- `*_batter_game_stats.csv`
- `*_pitcher_game_stats.csv`
- `*_team_game_stats.csv`
- `*_match_events.csv`

能力結果がない従来runでは追加ファイルを生成しない。

## 今後

Stage 13C-4候補:

- pre-MAIN matchへの同契約展開
- SeasonOrchestratorでAbilityMainMatchResolverを標準選択可能にする
- GameStatsのSQLite保存
- 同一選手の複数試合集約

その後Stage 13Dでread model / rankingへ進む。
