# ADR-014: 試合乱数seedと選手identity seedを分離する

- Status: Accepted
- Date: 2026-10-07

## Context

AbilityMatchResolverはTournamentEngineから受け取るgeneration_seedをPlayerRosterGeneratorとMatchSimulatorの双方に使用していた。

SeasonOrchestratorではcompetitionごとに異なるseedを生成する。

そのため同じ2026年度・同じ学校でも、春大会と夏大会でplayer_id・能力・ロスターが変わる可能性があった。

個人成績のシーズン集計、学校ロスター表示、将来の通算成績では同一選手identityが必要である。

## Decision

seedを2種類へ分離する。

### match generation seed

試合の確率イベントを再現するseed。

competition / matchごとに変化する。

### team generation seed

PlayerRoster / PlayerAbility / TeamStrengthを生成するseed。

SeasonOrchestratorではシーズンseedを使用し、同一年中固定する。

MatchSimulationInputへoptional team_generation_seedを追加する。

未指定時は従来通りmatch generation seedをteam generation seedとして扱い、後方互換を維持する。

## Consequences

### 利点

- 同一シーズンのplayer_idが大会を跨いで安定する
- 春・夏・秋の個人成績を同一player_idで合算できる
- player masterを1選手1行で保存できる
- 試合seedを変えてもロスター・能力が変化しない

### 注意

- team generation seedを変えれば同年度でも別世界線のロスターになる
- 年度を跨ぐplayer_id継続は別問題でありStage 13Fで扱う
- MatchSimulationResult.generation_seedはmatch seedを意味し続けるため、team seedはresolver detail / player master provenanceで保持する
