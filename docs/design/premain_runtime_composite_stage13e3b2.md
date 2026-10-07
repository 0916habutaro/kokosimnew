# Stage 13E-3B-2 複合qualifier runtime

作成日: 2026-10-08

## 目的

Stage 13E-3Aでpre-MAIN共通runtime primitiveを導入し、Stage 13E-3B-1でFMT006のPOOL_RR→CROSS_PLAYOFF→MAINをlazy化した。

Stage 13E-3B-2では、既存TournamentEngineが一括実行していた以下のqualifier方式を、未来結果を生成せず段階実行できるruntime compositionへ接続する。

- FMT002 / FMT003 / FMT016 / FMT025: PRIMARY→REPECHAGEまたはSECONDARY、FMT025はRANKING
- FMT004: PRIMARY_TOP4→SECONDARY
- FMT005: PRIMARY_GLOBAL→REPECHAGE_GLOBAL
- FMT007: MAIN_KO
- FMT008: MAIN_KO→REP_DECIDERS
- FMT010: PRIMARY_BLOCKS→SECONDARY
- FMT011 / FMT013: PRIMARY_LEAGUE→SECONDARY
- FMT012: PRIMARY_ZONES→SECONDARY
- FMT014: PRIMARY→SECONDARY
- FMT015: PRIMARY→PRIMARY_REPECHAGE→SECONDARY
- FMT017: ZONE_RR→FIRST_PLACE_PLAYOFF→SECOND_PLACE_PLAYOFF

SEED_EVENT系FMT009 / FMT018〜024とFIRST_TOURNAMENT FMT026はStage 13E-3B-3の対象とする。

## 基本原則

### 1. dependent phaseは必要になるまで存在させない

prepare直後に生成するのは最初のphaseだけとする。

たとえばFMT002ではprepare時点でPRIMARYのみを生成し、REPECHAGEはPRIMARY完了後に初めてentrant cohortを確定して生成する。

FMT015も同様に、

PRIMARY完了
→ primary nonqualifier確定
→ PRIMARY_REPECHAGE生成
→ repechage survivor確定
→ SECONDARY生成

の順とする。

### 2. legacy run()を回帰oracleとして残す

既存 `TournamentEngine.run()` の一括実行ロジックは削除しない。

lazy runtime完走後の `CompetitionRun.to_dict()` をlegacyと比較し、

- stage execution
- output school IDs
- match ID
- phase code
- round
- group metadata
- score/winner metadata
- MAIN entrants
- outcome
- detailed match result sink

が一致することを要求する。

### 3. RNG namespaceを変更しない

既存helperと同じnamespaceを使用する。

- block forest partition: `{competition}:{stage}:{group}:{phase}:forest_partition`
- single elimination draw: `{competition}:{stage}:{group}:draw`
- round robin partition: `{competition}:{stage}:{group}:{phase}:pool_partition`
- round robin match: `{competition}:{stage}:{group}:{phase}:P{pool}:M{seq}:{team1}:{team2}`
- knockout match: `{competition}:{stage}:{group}:R{round}:M{seq}:{team1}:{team2}`

これによりseed再現とlegacy互換を維持する。

## runtime構成

### CompositeQualifierGroupRuntime

group単位の複合phase state machine。

保持する主な状態:

- format_model_id
- eligible_school_ids
- output_slots
- 現在までにactivateされたphase
- phase間で受け渡すsurvivor cohort
- 共通match result sink

`ready_matches()` は現在activate済みかつreadyな試合だけを返す。

`resolve_match()` / `resolve_ready_round()` 後にphase完了条件を評価し、必要なら次phaseをactivateする。

`resolve_all()` はlegacyのresolver call orderを維持するため、phase順・block/pool順に完走する。

### Fmt005GlobalQualifierRuntime

FMT005はstage groupが独立組合せ単位ではなく、全県一括drawであるため専用runtimeとする。

PRIMARY_GLOBAL完了前にはREPECHAGE_GLOBALを生成しない。

stage groupは最終outputのaccounting集計だけに使用する。

## mixed-model stage

CMP000113 / CMP000114のようにdefault formatとgroup overrideが混在するstageでは、各groupの実効format_model_idを確定してそれぞれCompositeQualifierGroupRuntimeを生成する。

全groupが完了するまでMAINはactivateしない。

## MAIN activation

qualifier全体がcompleteになった時点でのみ、

qualifier outputs
+ direct MAIN entries

を統合してMainTournamentRuntimeStateを生成する。

それ以前は

- MAIN entrants未確定
- MAIN bracket未生成
- MAIN MatchResolver呼出しなし

を保証する。

## Compatibility target

Stage 13E-3B-2専用回帰では対象20大会についてlegacyとlazyを比較する。

代表的な境界テスト:

- FMT002: PRIMARY終了前にREPECHAGEなし
- FMT005: PRIMARY_GLOBAL終了前にREPECHAGE_GLOBALなし
- mixed model: CMP000114
- detailed MatchResolver: call sequenceとmatch_simulation_results key一致

## 次工程

Stage 13E-3B-3:

- SEED_EVENT
- FIRST_TOURNAMENT / FMT026
- seed event→qualifier→MAIN
- seed event→FIRST_TOURNAMENT→MAIN
- seed-only event→MAIN

を同じlazy activation原則へ接続する。
