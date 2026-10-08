# ADR-025: result-dependent大会はplaceholderではなくdeferred structural buildする

- Status: Accepted
- Date: 2026-10-08
- Stage: 13E-3D-3

## Context

年間graphを自動構築するには、season開始時に162大会すべてを認識する必要がある。

一方、秋東京CMP000016のように、
当年夏優勝校が分からないとannual structural inputを正確に構築できない大会がある。

CMP000016では

- 東東京夏優勝
- 西東京夏優勝

の2校が一次予選を免除する。

その2校を除いた230 team unitでPRELIMINARYを構成するため、
season開始時に仮のdirect teamを置くと未来結果を漏らすだけでなく、
qualifier partition自体が誤る。

## Decision

plannerは大会の存在とdependencyだけをseason開始時に確定する。

同年result-dependentなstructural大会は
strategy=deferred_structuralとする。

planner時点では

entrant_school_ids=[]

を許容し、future participant placeholderを生成しない。

source dependencyが解決した後に

StructuralAnnualInputFactory.build_prefectural(
  competition_id,
  year,
  direct_main_entry_school_ids=resolved_direct,
  seed_event_bypass_school_ids=resolved_bypass,
  rng_seed=planned_seed,
)

を初めて実行する。

一方、前年秋成績や未materialize新人戦など
current-year future resultではない外部contextは
既存SeasonOrchestratorと同じdeterministic bootstrapでseason開始時に解決する。

## Consequences

### Positive

- future winnerをplaceholderとして入れない
- future direct entrantを公開しない
- 東京秋232校構造を依存確定後に正しく構築できる
- plannerは162大会すべてをseason開始時にtopological planへ置ける
- root/dependent lifecycleが明確になる
- legacy structural factoryを再利用できる

### Trade-offs

- AnnualCompetitionInputがseason開始時点で完全ではない大会が存在する
- plan templateとactivated annual inputを別概念として扱う必要がある
- structural factoryをruntimeへ注入する必要がある

## Follow-up

正式save/loadではplan strategyとplanned rng seedを保存し、
未materialize大会はAnnualCompetitionInput全体ではなく
deferred plan entryとして永続化する。
