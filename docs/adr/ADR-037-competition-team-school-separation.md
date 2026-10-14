# ADR-037: 大会出場チームと学校・永久選手IDの分離

- Status: **Proposed（未採用）**
- Date: 2026-10-14
- Context: Issue #261／Stage43G-103

学校IDを対戦team_idとして使う現行schemaと能力生成器は、農林・塩山のような合同枠を、元学校所属のまま保存・集計できない。Stage103は小規模read-only previewと拒否境界までに限定した。本ADRはschema migrationやwriter採用を認可しない。

提案する正本は以下。

|正本|キー／関連|不変条件|
|---|---|---|
|大会チーム台帳|year, competition_id, team_id, source_version|school namespaceと分離、過去年大会IDを解散後も保持|
|構成学校membership|year, competition_id, team_id, school_id|同一年大会のschool二重枠参加を拒否。学校master変更なし|
|大会登録選手簿|year, competition_id, team_id, player_id, origin_school_id, team_slot, source_roster_sha|20人規則を契約化、同人二重登録拒否、入学年／所属／永久IDを改変しない|
|完全A試合|year, competition_id, match_id, team1_id, team2_id, score, inning_scores|チーム側スコア、打撃チームのイニング。旧payloadとのversion判別|
|投打個人成績|match key, team_id, player_id, origin_school_id|永久identityと登録簿をjoin。投手の相手判定はteam_id|
|大会outcome|year, competition_id, ranked_team_ids, champion_team_id, match manifest|学校順位へ暗黙変換しない。全実試合・ledger封印を確認|
|学校参加index|school_id, year, competition_id, team_id, match_id|学校履歴から合同試合を発見。単独学校勝敗と合同参加を別表示|

学校年ロスター・永久identityは既存正本を維持し、名前によるID修復・所属付替えをしない。能力生成入力は元学校能力snapshotと独立team登録簿を受ける新型を検討し、現行SchoolRoster／TeamMatchInputを偽装しない。ロスターseed、登録簿recipe、対戦seedのfingerprintを分離する。

導入順序は、(1)新型と独立oracle、(2)version判別read-only readerと旧5版内容verify、(3)学校履歴・個人・team順位の表示／leaderboard契約、(4)小規模実2試合・故障注入と再読込、(5)資料が一致する32枠31実試合のopt-in限定writer。シード・BYE・未完了seal・部分commit・解散後閲覧を必須検証にする。旧save自動移行、本番資格／全国合同一般化、翌年ゲーム開始は別の認可と仕様を要する。

JSON／複数SQLiteの非原子性は継続し、原子性を主張しない。過去全件保管・Windows native close／rename/reopen・最終CIを維持する。学校チーム分離が成立する前の31試合拡張は採用しない。
