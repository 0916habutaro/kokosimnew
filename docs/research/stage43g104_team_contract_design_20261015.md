# Stage43G-104 大会登録簿と新試合入力契約

Issue #263。最新Stage103 mainから専用ブランチ。Windows Python3.12を主要受入、個人利用・非配布。以下を実装前の境界とする。ADR-037はProposedのまま。

## 実コードのID契約表

|実コード／値|現行の意味|Stage104での扱い|
|---|---|---|
|joint_team_fixture / entries.team_id|年大会の読取出場枠、FX103 namespace|新型も学校とは別namespace。旧previewへ戻して試合実行しない|
|players / CareerRosterArchive.player_id, school_id|永久選手ID、学校正本、入学年・学年|元学校と永久IDを維持。登録番号team_slotと元roster_noは別|
|school_intake / profile.school_id, entry_year|選手の元学校・入学年の能力補正|元Playerをそのまま生成器へ渡す。合同用の偽学校profileは作らない|
|team_strength / TeamStrengthSnapshot.school_id|単一校能力、lineup/staffの校ID|混在能力は拒否される。新型に独立した試験用能力要約と起用を持つ|
|match_contract / TeamMatchInput.school_id|対戦側ID。ただし全能力所属と同一校を要求|新TeamInput.team_idと登録player.origin_school_idを分離|
|PlayerAbilitySnapshot.school_id|元学校。validatorは対戦校と一致要求|元学校のまま新型内に保持|
|MatchEvent.offense/defense_school_id|攻守の対戦側|将来はoffense/defense_team_id。各playerは登録簿から元学校をjoin|
|TeamGameStats.school_id / Result.team1/2_school_id|チームスコア／対戦側|将来はteam_id。旧項目を上書きしない|
|Batter/PitcherGameStats.school_id|生成時は対戦側ID、検証時は選手所属も要求|将来はteam_id＋origin_school_id＋player_id。現行simulateは元学校を保持できない|
|match_simulator / simulate, _empty_*_stats|対戦校辞書を使い個人成績にも対戦IDを渡す|単純adapter不可。新完全A型と新driver・validatorが必要|
|tournament_bridge / cache, roster_provider|年・seed・schoolで正本と単一校能力を取得|合同登録簿をSchoolRosterへ再包装しない。旧resolverへ接続しない|
|engine / entrants, winners, ranking|学校master、資格、学校順位|年大会team順位が必要。旧planに合同IDを入力しない|
|HistoricalMatchArchive / team1/2_id, full A|学校としての対戦側と個人schoolの整合、school検索も対戦側OR|新保存型・版判別reader・参加indexの採用前には保存しない|
|CareerCompetitionOutcomes / ranked_school_ids|単独学校順位・優勝|合同勝敗を構成校に転記しない|
|career_longitudinal_read, career_player_records, career_history_browse_model|対戦校検索と永久ID・学校join|新学校参加indexが必要。既存8校／33校GUIには接続しない|
|legacy_backup_compatibility / 338入力catalog|製品再生のコード・データ版|新規独立moduleのみ。catalog変更なし。旧候補verifyはrestore認可でない|

## 採用する限定入力

製品とは独立したimmutable lab modelに限定する。年2026、大会CMP000041、4校80人、3チーム。学校正本はStage103のseed430103・初年度生成規則を再照合。team IDは`LAB104:2026:CMP000041:joint/solo1/solo2`。recipe/version、構成学校、年大会、学校正本SHA、登録番号、永久ID、元学校、入学年、学年、元roster_noとpositionを記録する。構成校は同一年大会で二重出場不可。元ロスター集合SHAと各学校のSHAを分ける。hashは出典一致の検証用で真正性署名ではない。

20登録枠はゲーム用自己生成仮定。選抜はStage103のPOSITION_SLOTSごとの学校交互・未使用最小roster_noを継続。合同は10人ずつ、投手5人。公式の登録制限・両校の実際の選抜割合とは主張しない。出典はjoint_team_fixture.pyのpreviewとgame_core/players.pyのPOSITION_SLOTS。

新試合入力は明示opt-in、固定match seed430104、学校能力seed430103。個人能力はSchoolAwarePlayerAbilityGeneratorの公開APIを元Playerへ適用し学校値を維持。起用recipeはlab版：各primary positionでcontact最大（同点player_id昇順）を選び、contact順に打順、投手はcontrol順。チーム能力は登録20人のcontact/power/fielding平均と投手control平均。これらは**既存TeamStrengthの代替値ではなく、入力の整合確認用要約**。旧確率モデルで使用したとは主張しない。

検証器は元学校正本から台帳／登録／能力／起用／要約を再構築し厳密型も比較する。recipe・年・seed・membership・欠損・重複・元学校・position・fingerprint・能力・打順の改ざんを拒否。modelはpathやsave/rootを受けず、DB writerも持たない。試験だけがTemporaryDirectoryの学校正本を保存し独立SQL/JSON/SHAで照合する。

## 実試合の停止条件と将来の出力

現行simulateは攻守辞書から各個人成績school_idを生成し、新型は元学校別の複数所属を持つ。正式な入力型があっても**完全A出力型とdriverの契約は未成立**。本Stageは0試合で停止し、legacy変換とsimulate入口を専用例外で拒否する。試合結果は未対応とGUIに明示。BYE／勝上り／32チーム31試合は未実施。

最小の次改修は、(1)新完全A result/event/stat型：年大会matchキー、team1/2、score/inningはteam、投打は永久ID＋元学校＋試合時team、(2)既存確率計算の副作用のない再利用APIを切り出し、新driverで辞書キー／投手交代／相手判定をteamで扱う、(3)イベントから個人成績とイニングを独立再集計するoracle。旧TeamStrengthのselection／metrics再利用も混在を受理する新APIを要する。既存validatorの所属検査削除やschool IDすり替えでは解決しない。

将来の保存案はADR-038（Proposed）を参照。既存saveを開かず、旧schema変更・本番restore・自動移行・既存slot上書き・履歴削除・全国対応・翌年度開始を実施しない。JSON／複数SQLiteの非原子性は維持。
