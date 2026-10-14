# Stage43G-102 マスター33校・完全A・保存・Windows履歴閲覧の報告

Issue #259、最新main `e3fca8a`から専用ブランチ `stage43g102-yamanashi33`。[入力監査・保存・画面設計](stage43g102_yamanashi33_design_20261014.md)に根拠と制約を記録した。

## 採用範囲

2026山梨夏CMP000041の公式概要は32チーム、出場校一覧には農林・塩山合同がある。マスター33校を公式参加33チームとして認定する条件は満たさない。**ゲーム内検証用33校大会**として採用し、マスターやverified_structureを変更しない。公式結果・代表資格をゲームの生成結果として主張しない。

現行summer_areaを縮小せず33校で構築し、実AbilityMatchResolver／TournamentEngineの製品変更前dry runで64枠63ノード・31 bye・32実試合・全33校MAIN順位を確認した。ゲーム内試合日と件数は7/5:1、7/6:16、7/7:8、7/8:4、7/9:2、7/11:1。公式公表会期7/5–7/22の個別試合日や32チームの実ブラケットを再現したものではない。dry runは7.133秒（Linux補助、初期ロスター生成を含まない）だった。

新しい明示保存契約は2026・CMP000041・固定33校・確認済plan・外部入力版・組込み生成recipeだけを受理する。年seed2026101201、大会seed118436847、ロスターseed430102を分離し、初回manualで試合0件でも全33校660架空選手の正本と永久IDを保存する。既存Stage100/101・無指定service・8校demoの契約を維持する。

## 検証結果

最終製品差分のPython3.12ローカル専用14件（535.373秒）、Stage100/101保存・互換回帰26件（313.619秒）、全Python unittest2251件（1822.878秒）、関東17校E2E2件（684.732秒）はすべて成功。全suiteの環境別skip47件（新規native Tk1件を含む）と、専用製品・関東のskip0を区別する。製品コードhead `021b0df` の[Stage102専用CI](https://github.com/0916habutaro/kokosimnew/actions/runs/38569091043)でもWindows headless14件・Windows native Tk1件・Linux補助14件/Tk1件が全成功・skip0。

|実測対象|Linuxローカル Python3.12.14|根拠・範囲|
|---|---:|---|
|33校初期正本生成＋初回manual|0.792秒|試合0件、660人の保存|
|最初17試合＋autosave|3.500秒|7/5–7/6の実runtime|
|残り15試合＋autosave|19.679秒|明示load後、年末まで進行。試合日は7/7–7/11|
|32試合進行合計|23.179秒|上記2区間の計測合計。replay時間を含まない|
|年度封印＋1 outcome|2.082秒|完全ledger、MAIN全33校順位|
|全33校・全660人の履歴集計閲覧|3.412秒|独立SQL oracleとread-onlyモデルの全件照合|
|最終セーブの全ファイル|5,823,761 bytes（約5.55 MiB）|JSON manual/autosave、metadata、roster/archive SQLite合計。backups0|
|Windows native mapped Tk gate|47.073秒|Python3.12.10、別プロセスreplayを含む試験全体。全33校選択、32試合、順位、選手、終了／native close|
|Linux CI補助|製品14件392.907秒／mapped Tk1件39.822秒|Windows製品の代替ではない|

個別性能値は固定閾値にせず、実行環境・並行回帰の負荷を含む測定として扱う。初期サービス構築と繰返しreplay・故障試験は32試合進行合計に含めない。aggregate実測は `audits/phase2/stage43g102/product_linux_20261014.json`、全回帰は `local_validation_20261014.json`。Windows各段階のaggregateは上記workflowの公開JSON artifactでも閲覧できる。

- 新規→17試合→manual/autosave→別プロセスで両source明示load→残り15試合→年度封印→1 outcome→両source再ロード・繰返し保存を検証済み。既存行とロスター／identity不変、全32試合のスコア・イニング・投打／チーム成績・日付・永久ID参加対応、年度ledger、全33校順位を独立SQL/JSON/SHA oracleで照合する。
- 全33校の学校戦績と660人全員の個人累計をSQL原本から独立集計し、製品read-onlyモデルと照合する。名前joinや欠けた個人成績の補完はしない。
- JSON直後、学校1校目／33校目commit後、17試合archive commit後、seal前後、outcome commit後の応答前停止を注入。同一checkpointを別プロセスで再試行し、stale save・異なる日付checkpoint・ID／所属／学年／seed／設定／payload／ledger／outcome衝突を上書き前に拒否する。
- 接続・例外frameを保持した状態でnative closeをassertし、rename→reopen→integrity_checkを行う。JSON／roster／archive／outcomeは非原子的で、電源断や任意破損・並行writerの原子性を保証しない。
- 33校専用read-only Tkは学校候補30＋3、全33校選択、全32試合の完全A表示、大会詳細・ゲーム内33校順位、永久ID選手履歴と終了後のDB接続解放を必須gateで検証済み。個人Windows PCの目視・手操作とは報告しない。

Stage94/99/100/101の真のGit checkoutを別プロセスで自己生成export／verifyした候補は変更後にread-only内容verifyを受理し、現行replayは拒否する。Stage101候補はcatalog対象編集前にも生成・verify済み。固定338入力集合、master106 CSVとdata全bytesを維持する。catalog対象変更はlive_game_service.pyだけ、残り337入力不変。旧4版の内容検証許可は真正性証明・本番restore許可ではない。

専用Windows Python3.12 headless14件・本物native mapped Tk1件、Linux補助とローカル全回帰は成功。報告と集計JSONを確定した最終headについても、既存Stage94以降backup・Stage100/101・Windows SQLite/Tk・全Python・関東17校を含む全CI成功をPRに記録してから停止する。公開artifactは集計JSONだけで、秘密／既存save／絶対path／個別SHAを含めない。ローカル所定rootの既存save候補は0件、既存saveの内容検証・入力利用0。

## 未達の実大会条件・非対象

公式32チームと合同所属の完全なqualification、公式シード・個別対戦日、公式2026結果の再現は未達であり、実大会完成とは判定しない。現行33校runtimeと製品保存・架空履歴の段階検証に範囲を限定した。日程・合同チームの正式対応は別Stageの入力監査と保存契約が必要。

春資格の未確認事項、複数大会の一般統合、全国GUI、pre-MAIN／地区／feeder／選抜／免除、2027以降の開始、既存save接続・上書き・migration・削除、restore/import/activation、配布機能は実施しない。年度封印から翌年のゲーム開始を推論しない。

全最終head CI成功をPRに記録し、未マージ・auto-merge無効でレビュー待ちにする。
