# ADR-026: live season saveはobject serializationではなくdeterministic replayで復元する

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3E-1

## Context

Stage 13E runtimeはMAIN・pre-MAIN・SEED_EVENT・dependencyなど
複数のnested runtime objectを持つ。

Python dataclass / callback / defaultdict等をpickleして保存すると、

- class field追加
- module移動
- runtime内部構造変更
- resolver object変更

でsave互換性が壊れやすい。

一方、現在の試合生成はyear / seed / structural inputから
再現可能な設計になっている。

また未来結果を作らないというStage 13E原則上、
saveに未来bracket結果を入れたくない。

## Decision

save v1は内部object graphをserializeしない。

以下を保存する。

- plan identity fingerprint
- season clock
- processed date event log
- completed MatchResolution
- dependency state
- activation date
- public snapshot fingerprint
- resolver contract

load時は同一planからfresh runtimeを構築し、
processed dateまでdeterministic replayする。

replay結果をstored completed resultと完全比較する。

不一致はload error。

## Why completed results are still stored

seedから再生成できる場合でも、
save fileは「その時実際に起きた結果」を監査可能であるべき。

stored resultはreplay oracleとして使用する。

特に、

- score
- score_source
- ability_detail

まで比較することで、
同じwinnerだけ偶然一致したケースを見逃さない。

## Resolver requirement

v1のrestoreはsaved resultを強制注入せず、
同じresolverで再演算する。

そのためresolver_contract内ではseed deterministicである必要がある。

契約名が変わればcompatibility error。

契約名が同じでも出力が変わればreplay error。

## Plan mutation

competition master / school membership / schedule / dependency rule等が変わり、
planner outputが変わった場合はplan fingerprint mismatchで拒否する。

v1では自動migrationしない。

古いsaveを新masterへ曖昧に当てはめるより、
明示的migrationを将来versionとして実装する。

## Consequences

### Positive

- runtime内部実装をsave schemaから分離
- future resultをsaveしない
- corruption / model driftを検出
- deferred competitionを自然に再現
- JSONで監査可能
- ability detailまで再現検査可能
- save/load後の未来進行も同一seedで継続

### Trade-offs

- load時に過去日付をreplayするため、season後半ほどload costが増える
- non-deterministic resolverをv1では扱えない
- master更新後はmigrationなしでは旧saveをloadできない

## Follow-up

load性能が問題になった場合は、
version付きruntime checkpointを補助cacheとして追加してよい。

ただしcanonical source of truthはevent/result saveを維持する。
