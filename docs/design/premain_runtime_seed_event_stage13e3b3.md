# Stage 13E-3B-3 SEED_EVENT / FIRST_TOURNAMENT lazy runtime

作成日: 2026-10-08

## 目的

Stage 13E-3B-2までにqualifier→MAINの主要formatをlazy化した。

Stage 13E-3B-3では残るSEED_EVENT系graphを、未来結果を事前生成しないruntimeへ接続する。

対象graph:

- SEED_EVENT → MAIN
- SEED_EVENT → FIRST_TOURNAMENT(FMT026) → MAIN
- SEED_EVENT → qualifier → MAIN

対象seed model:

- FMT001
- FMT009
- FMT018
- FMT019
- FMT020
- FMT021
- FMT022
- FMT023
- FMT024

## runtime構成

### SeedGroupRuntimeState

seed-event group単位のlazy runtime。

FMT001:
- SEED_BLOCK_KO
- 全block winner確定後にseed ranking確定

FMT009 / 022 / 023 / 024:
- single elimination ranking
- SEED_KO / CENTRAL_KO / DISTRICT_KO

FMT018 / 020:
- PRIMARY_SEED_KO
- primary完了後にのみSEED_REPECHAGEまたはTHIRD_SEEDを生成

FMT019 / 021:
- PRIMARY_LEAGUESまたはDISTRICT_RR
- primary standings確定後にのみRANKING / CROSS_DECIDERSを生成

annual group_rankingsが入力されたgroupは既知の年次入力として扱い、試合生成なしでranking overrideを適用する。

### SeedEventRuntimeState

SEED_EVENT全体を管理する。

- group runtimeをofficial group順で保持
- seed_event_bypass_school_idsを適用
- linked seed ruleからforced seed assignmentを構築
- 全group完了後にcompetition_seed_rulesからSeedAssignmentを生成
- legacyと同じgroup_outputs / group_models / group_metadataをStageExecutionへ出力

## graph activation

### seed-only → MAIN

SEED_EVENT完了まではMAINを生成しない。

seed assignment確定後に全大会entrantをMAINへ入れ、destination_stageがMAIN系のseed metadataのみMAIN drawへ渡す。

### 岐阜秋

SEED_EVENT
→ seed対象校確定
→ 非seed校からFMT026 FIRST_TOURNAMENTを生成
→ gate winner確定
→ seed校＋gate winnerをMAIN entrantとして確定
→ MAIN生成

FIRST_TOURNAMENTはseed event完了前には存在しない。

MAINはFIRST_TOURNAMENT完了前には存在しない。

### 愛媛秋

SEED_EVENT
→ seed校確定
→ PRELIMINARY_QUALIFIER生成
→ seed校を16代表blockへ別blockになるよう分散
→ qualifier完了
→ MAIN16校確定
→ MAIN生成

seed情報は予選組合せの保護に使用し、MAIN seedingへは持ち越さない。

## explicit block forest

愛媛のseed context付きFMT001を再現するため、BlockForestRuntimeStateへcreate_from_blocks()を追加した。

これにより、seed_block_order / seed_order / nonseed_fill namespaceで作成した明示blockを、既存single elimination runtimeでlazy実行できる。

## compatibility contract

legacy TournamentEngine.run()をoracleとして維持する。

対象9大会:

- CMP000072
- CMP000073
- CMP000110
- CMP000116
- CMP000140
- CMP000144
- CMP000158
- CMP000160
- CMP000162

同一annual input / RNG seedでCompetitionRun.to_dict()完全一致を要求する。

岐阜秋ではdetailed MatchResolutionでも

- resolver call sequence
- match_simulation_results
- stage execution
- MAIN entrants

を完全一致させる。

## 統一入口

TournamentEngine.prepare_competition_runtime()を追加し、

- MAIN only
- qualifier → MAIN
- SEED_EVENT based graph

をstage構成からdispatchする。

## 次工程

Stage 13E-3Cでは、ここまで作ったcompetition runtimeをSeasonRuntimeState / 日付別scheduleへ接続し、実際のゲーム内current_dateによってpre-MAINからMAINまで試合を発火する層へ進む。
