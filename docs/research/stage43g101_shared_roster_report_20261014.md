# Stage43G-101 同年度2大会・共通ロスター保存の検証報告

Issue #257、PR #256マージ後main `bd83cec`から`stage43g101-shared-year-roster`を作成。[設計書](stage43g101_shared_roster_design_20261014.md)に生成元・2大会の選定・拒否対象・保存順序と故障境界を記録した。

## 実装結果と範囲

- 新しい明示契約`SharedSchoolYearPersistence`は、2026山梨春／夏の**自己生成4校×2大会fixture**だけを受理する。共通2校・union6校120選手・6実試合を既存`LiveGameService`／`TournamentEngine`で処理した。春大会の公式資格・全校構造は未確認であり、一般の実大会向け契約を開放したという意味ではない。
- 年seed2026101201、大会seed263372546／118436847、学校ロスターseed430101を分離。新規runtime／replay前に学校年度正本を固定し、学校集合unionを初回manualから一度保存する。別大会で新規選手を生成せず、同じ永久ID・所属・入学年・学年で個人成績をjoinした。
- 既存Stage100の8校・160選手・単大会7試合契約と無指定serviceは維持。共通validatorを対象大会別に照合する最小差分とし、新契約の別plan／別契約名・未証明provider・事後cache・学校不足・identity変化・pre-MAIN・依存／同日大会・翌年度は拒否する。
- 両大会のスコア・イニング別得点・打撃／投手成績・試合日、学校戦績と個人通算、年度ledger、MAIN順位と元試合manifestを独立raw SQL／JSON／SHA oracleで照合した。片方未完了のyear_end_readinessは全対象2大会を数え、封印／outcome確定を拒否する。
- JSON、学校別roster、試合、年度封印、大会別outcomeは複数commitで非原子的のまま。同一checkpointのみ再試行し、古いsave・変更identity・SQL索引列／payload不一致・ledger／outcome変更はJSON更新前に拒否する。任意破損の修復、電源断耐性、並行writerの原子性は保証しない。

## 検証

|項目|結果／受入条件|
|---|---|
|Stage101製品・旧候補専用headless|Python3.12で12件成功・skip0。初回manual→春autosave/manual→両source別プロセスload→夏3試合→全年度封印→両outcomes→両source再ロード／2回再保存|
|故障境界|JSON直後、最初／最後の学校commit後、片方大会の試合archive commit後、seal直前／直後、片方／両outcome commit後の応答前停止を注入。別プロセスreplay後、6 rosters／120 identities／6 games／2 outcomesに一致。native handle／例外frameを保持して製品closeをassert|
|読み取り境界|両大会の学校戦績・各選手通算をSQLから独立集計。閲覧前後の全bytes不変。同一checkpoint再保存のDB bytes不変を、進行・load修復による書込みと区別|
|Stage94/99/100旧候補|真の固定Git checkoutを別プロセスでexportして内容verifyを受理。現在replayはcatalog_mismatch_refused／allowed=false。候補内容は変更せず、真正性の証明や候補内code実行は行わない。Stage100候補は製品編集前にも私的一時領域へexport・verify済み|
|338入力・master106 CSV|固定入力集合維持。catalog対象変更はlive_game_service.pyだけ、残り337入力とdata全bytes不変。旧3版digestを維持し、新固定版を追加。公開artifactに個別private SHA／path／候補／evidenceを含めない|
|Windows重点CI|専用Python3.12製品12件とnative mapped Tk1件をzero skipsで必須。実SQLite close→終了後rename／再読取／integrity_check。既存Stage94–100 CIも維持。最終headの成功はPRで記録|
|Tk|自己生成2大会を別プロセスload／seal後、既存read-only Tkで共通校・両大会の完全A・永久ID個人成績を表示し、bytes不変と製品closeを検証する。Stage98/100の8校デモUIは変更なし|
|ローカルGUI環境|実行サンドボックスがXサーバーのlistening socket作成を拒否し、Tk起動不可。ローカルTk成功とは報告しない。Windows／Linux専用CIで検証する|
|全Python unittest／関東17校|Python3.12全suiteと関東8都県17校専用2件を実行。全suiteで既存規約どおり関東重複実行をskipし、専用E2Eで全処理を検証。環境別skipと専用zero skipsは区別し、最終結果はPRで記録|
|既存save|環境に候補JSON2件をファイル名・件数だけ確認。内容を開かず入力利用0件・未検証。CI自己生成以外の候補を使用しない|

## 未対応・次工程

山梨春の正式資格、全国春秋県・地区・夏・全国大会の全方式、地区feeder／pre-MAINの共有正本、選抜・予選免除、翌年資格／roster advance、年次自動進行は完成していない。翌年台帳の登録を実試合開始とは呼ばない。実資格を証明した同県2大会の正式契約への拡張は別Stageの判断とする。

新複数大会GUIの操作画面／学校フィルタは設計書の次工程仕様だけ。正式全国GUI、EXE／インストーラー／配布署名／自動更新、既存save移行／restore／import／activation、履歴削除、年数上限は追加しない。個人Windows PCでの目視・手操作は未検証。

全PRチェック成功後もPR未マージ・auto-merge無効でレビュー待ちにする。
