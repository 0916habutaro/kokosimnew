# ADR-011: 全大会stageは共通MatchResolution、GameStatsはSQLiteへ永続化する

- Status: Accepted
- Date: 2026-10-07

## Context

MAINだけ能力モデルへ移行した状態では、地区予選・seed event・敗者復活等の勝敗がlegacy random resolver、MAINがability modelとなり、一大会の中で試合モデルが分断される。

また、CompetitionRun内にGameStatsを保持するだけではプロセス終了後に個人成績を検索・集約できない。

## Decision

### 1. resolver

Phase 2の全pre-MAIN primitiveとMAINは共通の `MatchResolution` 契約を利用可能にする。

TournamentEngineへ `match_resolver` を指定した場合、全stageへ適用する。

resolver未指定時はlegacy behaviorを維持する。

### 2. Season

SeasonOrchestratorはgeneric resolverをconstructor injectionで受け取り、TournamentEngineへ渡す。

game_coreへの直接依存は作らない。

### 3. persistence

Stage 12R BrowseRepositoryをschema v2へ拡張し、

- ability match
- batter GameStats
- pitcher GameStats
- team GameStats
- MatchEvent

をSQLiteへ保存する。

率指標は保存せず、Stage 13C-1で決めたcount正本方針を維持する。

## Consequences

### 利点

- 予選から決勝まで同じ能力モデルを使える
- Season単位で試合モデルを切替可能
- individual statsをプロセス終了後も検索できる
- Stage 13Dのread modelをSQLite上で構築できる
- legacy構造監査を維持できる

### 注意点

- ability full seasonはlegacyより計算量が大きい
- SQLiteには現時点でGameStatsは保存するがPlayerAbility snapshot自体は保存しない
- schema v2 migrationは追加table方式で、既存browse tableを破壊しない

## Backward compatibility

- default CLI = legacy
- TournamentEngine(repo) = legacy
- AbilityMainMatchResolver旧名 = alias
- main_match_resolver引数 = 維持
