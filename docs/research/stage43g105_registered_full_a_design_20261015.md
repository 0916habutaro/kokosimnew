# Stage43G-105 登録チーム完全A隔離実験（2026-10-15）

## 実行前の契約調査と不変条件

旧match_contractのTeamMatchInput.school_id、MatchSimulationResult.team1/2_school_id、team_stats.school_id、event.offense/defense_school_idは対戦側を示す。一方PlayerAbilitySnapshot.school_id、Player.school_id、Batter/PitcherGameStats.school_idは元学校を示す。旧MatchSimulatorは後者へ対戦側school_idをコピーするので合同入力を渡せない。TeamStrengthGeneratorは単一school_idを要求し、打順9人・先発P・投手順・守備合成値を学校単位で生成する。SchoolAwarePlayerAbilityGeneratorは元学校と入学年から能力を生成する。AbilityMatchResolverは学校別の選手簿/能力/チームキャッシュと大会勝上りを接続する。

HistoricalMatchArchiveはteam1/2_idを学校として旧school_id成績と照合する。CareerPlayerRecordView（IssueのCareerPlayerRecords相当）は元学校で永久IDを検索し、試合参加側にも同じ学校を要求する。CareerHistoryBrowseModelも学校別履歴・旧Aとv2 sandboxを読む。これらは新team結果のreader/writerではない。旧入力・検証器・計算・保存・restore・閲覧には変更しない。

|対象|正本|実行前/後の不変条件|
|---|---|---|
|登録|Stage104 CompetitionRegistration|4校80永久ID、3team、各20枠、60枠で二重登録なし|
|能力|RegisteredAbility.snapshot|school_idはorigin_school_id、永久IDは元登録と一致|
|対戦|RegisteredMatchInput|明示opt-in、異なる登録team、年2026/大会CMP000041/試合IDを全行に保持|
|攻守|年大会team_id|先攻team1/後攻team2、打者は攻撃側、投手は守備側に登録|
|打順|入力9人|循環順、P交代時は同一打順枠を後任Pに置換、退出P再登場なし|
|投手|入力pitching_order|先発は初期P、3打者以上対戦後の能力依存上限で次投手へ、責任走者を保持|
|得点|実行イベント|走者永久ID、塁/アウト連続、個人得点合計=team得点=イニング合計=相手投手失点|
|完全A|新versioned型|全打撃/投手カウンタ、team得点/安打/失策、イニングと結果を独立再集計|
|終了|新labルール|9回、後攻リードの裏省略、サヨナラ、同点延長、30回同点は結果なしで拒否|
|保存|メモリ/所有TemporaryDirectory|旧writer無接続、全338catalog入力と106CSV不変|

## 新型と計算範囲

`registered_team_full_a_v1`は年/大会/試合、team1/2_id、seed、入力SHA、確率設定SHA、モデル識別、全イベントと完全Aを持つ。個人行はteam_id/player_id/origin_school_idを分離。旧school_idを含まない。JSON読込は完全なキー集合・型・versionを検査し、authoritiesを再検証してから独立oracleを実行する。SHAは整合確認用であり真正性署名ではない。seed変更は明示run_seed引数で選択し、検証時もexpected_seed指定が必要。Stage104入力内の固定seedは改変不可。

既存MatchSimulator._event_weightsの能力依存確率だけを、元学校を保持したsnapshotに適用する。独立driverでK/BB/HBP/単打/二塁打/三塁打/本塁打/通常アウトを抽選。旧エラー/野選の重みは通常アウトへ加算する。守備値は登録先発8野手のfielding算術平均。進塁は安打塁数分の確定進塁、四死球は押出し。旧走塁確率・犠打/犠飛/エラー/盗塁は採用しないため関連成績は0。失策なしなので自責点=失点。投手交代後も各走者を出した投手へ失点を帰属。単打等のサヨナラは必要勝越し走者まで得点、HRは全走者得点。コールド/タイブレーク/公式2026ルール再現は未対応。投手交代は旧能力依存BF上限式を再利用、3打者以上でのみ実施。投球球数モデルはなく、対戦打席・投球アウト・奪三振を検証する。

これは旧確率の部分流用による新labモデルであり「同一エンジン実試合」ではない。固定スコアや後付け元学校ラベルは禁止。独立oracleはdriverの進塁/集計を呼ばず、イベントの塁移動を数値位置で再構成し、打順・交代・走者責任と全成績を再集計する。別途同seedイベント再実行で確率/seed/改ざんを照合する。

## 次Stageの仕様（未採用）

新readerはdiscriminator/年大会試合複合キー/入力と登録SHAを必須とし、team別スコアとorigin別選手検索を分ける。append-only独立lab storeは自己所有領域だけ、既存行同内容の再追加のみ許可、異内容競合は拒否。Option Aの結果本体と登録正本参照を保持し、イベントは検証証拠として任意別保管。旧archiveへの変換は禁止。reader/writer/schema採用と製品GUI・大会接続は別Stageで審議。ADR-037/038はProposedのまま。
