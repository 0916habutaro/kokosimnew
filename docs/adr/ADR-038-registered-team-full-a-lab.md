# ADR-038: 登録簿を参照するteam別完全Aと読取版判別の候補

- Status: **Proposed（未採用）**
- Date: 2026-10-15
- Context: Stage43G-104 / Issue #263、ADR-037を継続

Stage104の固定自己生成labでは学校正本／出場チーム／永久選手を分離した登録簿・能力入力が成立した。現行simulateの成績生成は対戦school_idを個人school_idに書くため、完全A再利用は入力adapterでは解決できない。実試合0件、新保存型未実装。製品match_contractとarchiveを変更しない。

次Stageの候補は以下。採用やwriter実装の認可ではない。

|契約|具体的候補と導入条件|
|---|---|
|新入力／出力版|`registered_team_full_a_v1`の明示discriminator。旧無版payloadはlegacy school形式として検証し、新形式の旧readerへの暗黙流入を拒否|
|チーム正本|year/competition/teamとimmutable membership・登録簿、学校正本SHA、recipe版を別に保持。解散後も全件閲覧可能|
|完全A|score、inning、team_statsはteam_id。batter/pitcher statsはplayer_id＋origin_school_id＋team_id。eventsの攻守はteam、出現永久IDの所属は登録簿照合|
|実行部|旧確率計算のpure boundaryを抽出し、新driverにteam辞書と元学校mapを別に持つ。投手交代・相手判定・イベント再集計を独立oracleで確認|
|新能力|混在登録を受ける正式なlineup/staff/metrics API。Stage104の平均要約・contact/control起用は試験用で、旧TeamStrengthの意味を置換しない|
|保存とreader|新形式専用のappend-only storeと版判別readerを先にfixtureで検証。HistoricalMatchArchiveの旧schemaはそのまま読み続け、旧payloadを書き換えない|
|学校参加index|school_id/year/competition_id/team_id/match_idを登録membershipから作る版管理派生index。学校→参加チーム→試合、個人→永久ID＋元学校＋試合時teamを表示。構成校に合同勝敗・優勝を転記しない|
|順位|ranked_team_ids/champion_team_id。単独学校順位と別表示。集計分母と合同参加扱いを仕様化してからleaderboardを採用|
|rollback|writer無効化で新レコードを保持してread-only化、旧saveは旧readerへ戻す。旧save移行・既存slot上書きでrollbackしない。新登録簿欠損はfail closed|
|故障回復|自己生成専用labで部分保存・欠損登録・未完了seal・BYE／勝上り・SQLite releaseを検証後に採用判断。複数store原子性は別課題であり保証しない|

旧Stage94/99/100/101/102/103の内容verify、版とdigest一致、旧replay拒否を維持する。真正性署名・本番restore/import/activation・全国合同・翌年度開始・履歴GCは別の仕様と認可を要する。Stage104ではこれらを導入しない。
