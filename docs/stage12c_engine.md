# Phase 2 Stage 12C-4 — 県大会MAIN本戦の組み合わせ生成・全ラウンド進行

## 到達点

Stage 12B で定義した `FMT001` ～ `FMT026` の **全26 format model** を、
`phase2_engine.TournamentEngine` の共通実行器へ接続した。
大会名ごとの専用処理ではなく、stage/group に割り当てられた `format_model_id` と
`competition_stage_format_parameters.csv` を読んで処理する。

Stage 12C-1 / 12C-2 で実装済みだった岐阜・北海道・千葉・神奈川・青森の経路を保持し、
Stage 12C-3 では残り17方式を追加した。

## Stage 12C-3で追加した方式

- `FMT002` 本戦＋敗者復活で所定枠を選出
- `FMT003` 一次予選＋条件付き二次予選
- `FMT004` 上位4校保護＋二次代表トーナメント
- `FMT007` トーナメント上位4校＋順位決定
- `FMT008` シード決定→本予選4＋敗者側2
- `FMT010` 一次ブロック1・2位決定→二次トーナメント
- `FMT011` 一次リーグ→二次トーナメント
- `FMT012` 一次ゾーントーナメント→決勝/順位決定
- `FMT013` 一次リーグ各組上位2→二次トーナメント
- `FMT014` 一次トーナメント→二次トーナメント
- `FMT015` 一次トーナメント＋敗者復活→二次トーナメント
- `FMT016` 一次代表決定＋二次敗者側代表決定
- `FMT017` ゾーンリーグ＋1位/2位代表決定戦
- `FMT022` 中央大会トーナメント・ベスト4でシード権確定
- `FMT023` 地区トーナメント上位N校を順位で抽出
- `FMT024` 地区シード決めトーナメント上位N校
- `FMT025` 予選＋敗者復活＋順位決定

既実装の `FMT001 / 005 / 006 / 009 / 018 / 019 / 020 / 021 / 026` と合わせ、
26/26方式が実行器のサポート対象になった。

## 共通プリミティブ

17方式を17個の大会専用ロジックとして実装せず、主に次の共通処理へ分解した。

1. 指定枠数の代表を選ぶ block-winner forest
2. 単一トーナメントの順位生成
3. 一次予選→敗者復活/二次予選
4. 複数リーグ→二次トーナメント
5. 一次トーナメント→二次トーナメント
6. ゾーンリーグ→1位/2位代表決定
7. seed-only大会の上位N校/ベスト4/ブロック勝者抽出

勝敗は引き続き namespace 付きSHA-256派生seedによる再現可能な50/50 resolverを使用する。

## 年度固有入力

`AnnualCompetitionInput` は次を受け取る。

- `entrant_school_ids` — その年度・大会の実参加校
- `direct_main_entry_school_ids` — 予選免除・推薦等でMAINへ直接入る学校
- `group_rankings` — 公式順位が既知の場合の順位上書き
- `group_pool_assignments` — 公式リーグ組分けが既知の場合のpool上書き
- `group_entrant_school_ids` — 年度固有の地区参加校上書き

`group_entrant_school_ids` は Stage 12C-3 で追加した。三重のように現在の恒久地区所属マスターに
学校対応が未登録でも、年度の大会参加校を地区別に渡せば同じengineを使用できる。
指定校は必ず `entrant_school_ids` の部分集合でなければならない。

## 年間抽選カードとの分離

Stage 12B が保持するのは「制度・phase・進出枠」であり、2026年の全対戦カードそのものではない。
そのため年度抽選が与えられない場合は、制度と総枠数を守った決定論的シミュレーションdrawを生成する。

特に `FMT002 / 003 / 016 / 025` など、一次と敗者復活/二次の**年度別の細かな枠配分**が
Stage 12B CSVに明示されていない方式では、総進出枠を守る再現可能なphase splitを生成し、
`metadata.annual_phase_split_policy=deterministic_simulation_from_total_quota` として記録する。
これは公式2026カードを推測して固定するものではない。

## 構造検証

Stage 12C-3追加対象の23大会を全実行し、すべて成功した。
代表例:

- 岩手春秋 / 福島春秋 / 岐阜春 / 兵庫秋: `FMT002`
- 宮城春秋: `FMT003`
- 茨城秋: `FMT004`
- 長野春: `FMT007`
- 長野秋: `FMT008`
- 愛知春秋: `FMT010`～`FMT015` mixed
- 三重春: `FMT016`
- 岡山秋: `FMT017`
- 徳島秋 / 沖縄秋: `FMT022`
- 鹿児島秋: `FMT023`
- 三重秋: `FMT024`
- 静岡春秋 / 広島春秋: `FMT025`

Stage 12C-1 / 12C-2 の方式も回帰テスト対象に含める。

## 現段階の境界

- 勝敗はまだ学校・選手戦力に連動していない。
- 年度固有draw未入力時は公式2026対戦カードではなく制度準拠のシミュレーションdrawになる。
- `competition_access_rules` / `competition_seed_rules` の「前年大会結果等から対象校を検索するresolver」は、
  現在は年度入力との境界までで、過去シーズン結果DBからの自動解決は後続工程。
- seed-only大会は県大会参加資格を削らずseed metadataだけを重ねる。
- MAIN県大会本戦の全ラウンド生成、日程進行、試合結果保存、ゲームUI接続は次工程。

## テスト

```bash
python -m unittest discover -s tests -p 'test_stage12c*.py' -v
```

Stage 12C-1 / 12C-2回帰を含め **31/31 PASS**。


---

## Stage 12C-4 — MAIN本戦

Stage 12C-3までの `予選/seed event -> MAIN参加校確定` に続き、県大会MAINを実際に最後まで進める。
`prefectural_competition_index_2026.csv` の47都道府県×春秋94大会について、MAINは全件
`single_elimination` として扱う。

### 固定トーナメント表

MAIN参加校数以上の最小の2の累乗をbracket sizeとする。例えば37校なら64枠。
64-37=27のbyeは**1回戦だけ**に配置し、2回戦以降に新しいbyeを発生させない。
実試合数は常に `MAIN参加校数 - 1` となる。

年度の正確な抽選位置が未入力の場合は、構造化済みseedを標準seed位置へ分散し、
残りをnamespace付きseedで再現可能に抽選する。公式の未構造化抽選制約を推測して固定しない。

### Stage 12C-4で追加した年度入力

- `main_seed_school_ids` — MAIN用の年度固有seed順（強い順）
- `main_bracket_slots` — exact annual draw。空文字は1回戦bye
- `main_match_winner_overrides` — 実結果再生用 `match_id -> winner_school_id`

既存のseed eventで生成された `SeedAssignment` は自動的にMAIN抽選へ引き継がれる。

### 大会結果

`CompetitionRun.outcome` に以下を保存する。

- champion
- runner-up
- semifinal losers（ベスト4 cohort）
- quarterfinal losers（ベスト8 cohort）
- 全参加校の最終ranking
- round別敗退校
- 実試合数 / bye数 / bracket size

各MAIN matchには `round_name`, `next_match_id`, `next_match_side` をmetadataとして持たせ、
GUIでトーナメント表を再構築できる。

### 結果ファイル

`phase2_engine.results.save_competition_run()` は1大会につき次の3ファイルを出力する。

- `<competition>_<year>_summary.json`
- `<competition>_<year>_matches.csv`
- `<competition>_<year>_placements.csv`

CLIでは `--result-dir` で保存できる。公式抽選・公式結果を再生する場合は
`--main-draw-json` と `--main-winner-json` を使用する。

### 全国構造監査

47都道府県×春秋94大会を構造入力で完走させ、94/94 PASS。
Stage 12C-1～12C-3の回帰を含むunittestは39/39 PASS。

### 次工程

Stage 12Dでは、年度カレンダー・過去大会結果resolver・地域大会/全国大会へのqualificationを接続し、
47都道府県の春秋をシーズン単位で連続実行するエンドツーエンド監査を行う。


---

## Stage 12D — 全国47都道府県・春秋のシーズン単位エンドツーエンド監査

`phase2_engine.season.SeasonOrchestrator` を追加し、単発の大会実行からseason stateを持つ連続実行へ拡張した。

### 実行順

1. selection_rules quotaに基づく32校の**構造監査用**Senbatsu fixtureを生成（実際の2026出場校リストではない）
2. 前年秋結果DB未実装部分をdeterministic prior-year fixtureとして用意
3. 春47県大会を実行し、前年秋top-N / Senbatsu参加による予選免除をresolverで投入
4. 夏49地方大会を実行し、49 winnerをqualification_rulesで全国大会へ接続
5. 秋47県大会を実行し、当年夏winnerを宮城・福島・千葉・神奈川・静岡・兵庫等の直接出場へ自動投入
6. 三重秋は当年夏winnerをseed eventから除外し、`SDR000040` の8枠目seedとして追加
7. 秋地区winner→神宮の10 rulesを評価

### 結果

- 春47/47・秋47/47は技術的に完走しchampionを生成
- 公式構造とMAIN人数まで一致: 93/94
- 東京秋 `CMP000016`: MAIN64の前段一次予選が未構造化で、269加盟校が直接MAINへ入るためgapとして検出
- `competition_access_rules`: 17/17 resolver PASS
- 夏地方49/49 → 全国49代表 → 全国大会実行 PASS
- `qualification_rules`: 51/59 resolved
  - 夏49→全国: 49
  - 北海道秋・東京秋→神宮: 2
  - 残り秋地区8→神宮: source regionalが未実行のためBLOCKED
- 県大会→地区大会 feeder rule: 春8＋秋8=16大会が未構造化
- 県春秋calendar: 94中3件official、91件research_pending
- known date dependency inversion: 0

### 重要な設計境界

Stage12Dは未登録制度を推測して成功扱いにしない。県→地区大会の各都道府県枠、東京秋一次予選、未確定県大会日程はgap CSVへ明示する。
前年秋およびSenbatsuのfixtureも、過去結果DB/実選考リストが未接続な構造監査用であり、実在2026結果の再現とは区別する。

### テスト

`python -m unittest discover -s tests -p 'test_stage12*.py' -v`

Stage12C-1～C-4回帰39件＋Stage12D 11件 = **50/50 PASS**。


## Stage 12E — 春秋県大会→地区大会の進出ルール構造化

`regional_feeder_rules.csv` と `regional_qualification_playoffs.csv` を追加し、Stage12Dで未接続だった春8＋秋8の県大会→地区大会をseason engineへ接続した。

### 構造化内容

- feeder rule: **96件**
- 地区大会: **春8＋秋8＝16大会**
- 秋近畿の3位校出場決定戦: **2試合**
- 春九州: 九州地区の当年Senbatsu参加6校を先に採用し、重複を除外して各県枠を上位順位から補充
- ルール表には学校名・school_idを固定せず、県大会結果・選抜参加集合から動的に解決

### SeasonOrchestrator接続

春47県大会終了後に春地区8大会、秋47県大会終了後に秋地区8大会を自動生成・実行する。秋地区大会完了後は既存 `qualification_rules.csv` の地区優勝→明治神宮10枠をすべて解決し、10校で神宮大会まで実行する。

### 2026構造監査結果

- regional feeder: **96/96 PASS**
- regional playoff: **2/2 PASS**
- 地区大会: **16/16 PASS**（参加数が各大会の規定team_countと一致）
- Stage12D regional bridge gap: **16 → 0**
- 既存 qualification rules: **59/59 PASS**
- 秋10地区代表 → 明治神宮大会: **完走**
- unittest: **60/60 PASS**

### 残課題

- 東京秋 `CMP000016`: 269加盟校→MAIN64校となる前段予選が未構造化
- 県春秋94大会の正式日付: 91大会が `research_pending`

次工程は Stage12F として東京秋の前段予選を構造化する。


## Stage 12F — Tokyo autumn preliminary qualifier

- `CMP000016` now runs `PRELIMINARY_QUALIFIER -> MAIN`.
- 2026 structure is modeled as 31 numbered blocks, each with A/B representative brackets (62 qualifiers total).
- Current-year East Tokyo and West Tokyo summer champions bypass the preliminary and enter MAIN directly; 62+2=64.
- Observed 2026 participation is 260 schools / 232 team units. The current Phase 1 identity model is school-based, so structural audit uses 232 deterministic school proxies (230 preliminary + 2 direct) while preserving an explicit gap for exact combined-team mapping.
- Annual exact block membership can replace the proxy through `group_entrant_school_ids`; no school name is hardcoded in rule tables.
