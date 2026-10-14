# Stage43G-102 マスター33校・完全A・保存・Windows履歴閲覧の報告

Issue #259、最新main `e3fca8a`から専用ブランチ `stage43g102-yamanashi33`。[入力監査・保存・画面設計](stage43g102_yamanashi33_design_20261014.md)に根拠と制約を記録した。

## 採用範囲

2026山梨夏CMP000041の公式概要は32チーム、出場校一覧には農林・塩山合同がある。マスター33校を公式参加33チームとして認定する条件は満たさない。**ゲーム内検証用33校大会**として採用し、マスターやverified_structureを変更しない。公式結果・代表資格をゲームの生成結果として主張しない。

現行summer_areaを縮小せず33校で構築し、実AbilityMatchResolver／TournamentEngineの製品変更前dry runで64枠63ノード・31 bye・32実試合・全33校MAIN順位を確認した。ゲーム内試合日と件数は7/5:1、7/6:16、7/7:8、7/8:4、7/9:2、7/11:1。公式公表会期7/5–7/22の個別試合日や32チームの実ブラケットを再現したものではない。dry runは7.133秒（Linux補助、初期ロスター生成を含まない）だった。

新しい明示保存契約は2026・CMP000041・固定33校・確認済plan・外部入力版・組込み生成recipeだけを受理する。年seed2026101201、大会seed118436847、ロスターseed430102を分離し、初回manualで試合0件でも全33校660架空選手の正本と永久IDを保存する。既存Stage100/101・無指定service・8校demoの契約を維持する。

## 検証結果

初回の主要10製品テスト261.926秒、新しい入力版／異なるcheckpoint拒否2件7.695秒、旧4版候補互換2件19.322秒はいずれも成功・skip0。これらは初期ローカル差分の確認であり、最終headの専用集計・全回帰・Windows成功の代用にはしない。最終版の測定結果は専用aggregate JSONとこの報告の追記に記録する。

- 新規→17試合→manual/autosave→別プロセスで両source明示load→残り15試合→年度封印→1 outcome→両source再ロード・繰返し保存を検証する。既存行とロスター／identity不変、全32試合のスコア・イニング・投打／チーム成績・日付・永久ID参加対応、年度ledger、全33校順位を独立SQL/JSON/SHA oracleで照合する。
- 全33校の学校戦績と660人全員の個人累計をSQL原本から独立集計し、製品read-onlyモデルと照合する。名前joinや欠けた個人成績の補完はしない。
- JSON直後、学校1校目／33校目commit後、17試合archive commit後、seal前後、outcome commit後の応答前停止を注入。同一checkpointを別プロセスで再試行し、stale save・異なる日付checkpoint・ID／所属／学年／seed／設定／payload／ledger／outcome衝突を上書き前に拒否する。
- 接続・例外frameを保持した状態でnative closeをassertし、rename→reopen→integrity_checkを行う。JSON／roster／archive／outcomeは非原子的で、電源断や任意破損・並行writerの原子性を保証しない。
- 33校専用read-only Tkは学校候補30＋3、全33校選択、全32試合の完全A表示、大会詳細・ゲーム内33校順位、永久ID選手履歴と終了後のDB接続解放を必須gateで検証する。個人Windows PCの目視・手操作とは報告しない。

Stage94/99/100/101の真のGit checkoutを別プロセスで自己生成export／verifyした候補は変更後にread-only内容verifyを受理し、現行replayは拒否する。Stage101候補はcatalog対象編集前にも生成・verify済み。固定338入力集合、master106 CSVとdata全bytesを維持する。catalog対象変更はlive_game_service.pyだけ、残り337入力不変。旧4版の内容検証許可は真正性証明・本番restore許可ではない。

専用Windows Python3.12 headless14件・本物native mapped Tk1件、Linux補助、既存Stage100/101とStage94以降backup・Windows SQLite/Tk、全Python unittest・関東17校E2Eの最終結果を確認中。公開artifactは集計JSONだけで、秘密／既存save／絶対path／個別SHAを含めない。既存save候補は件数のみ・未検証、入力利用0。

## 未達の実大会条件・非対象

公式32チームと合同所属の完全なqualification、公式シード・個別対戦日、公式2026結果の再現は未達であり、実大会完成とは判定しない。現行33校runtimeと製品保存・架空履歴の段階検証に範囲を限定した。日程・合同チームの正式対応は別Stageの入力監査と保存契約が必要。

春資格の未確認事項、複数大会の一般統合、全国GUI、pre-MAIN／地区／feeder／選抜／免除、2027以降の開始、既存save接続・上書き・migration・削除、restore/import/activation、配布機能は実施しない。年度封印から翌年のゲーム開始を推論しない。

全最終head CI成功をPRに記録し、未マージ・auto-merge無効でレビュー待ちにする。
