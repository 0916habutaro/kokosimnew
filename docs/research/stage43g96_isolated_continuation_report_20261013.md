# Stage43G-96：隔離再ロード・続行の決定論監査報告

Issue #247、基点main `8cdb88676f1a78e3c93fe67ee3fe92b9df01a2c6`。[設計](stage43g96_isolated_continuation_design_20261013.md)に従い、製品コードを変更せずtests配下へ自己生成fixtureの比較ハーネス・故障試験・専用CLIを追加した。製品restore/import/activation APIや外部save/candidate/targetを指定するCLIは追加していない。

Stage94の実ゲームで生成した旧A8校単大会をexport/verifyし、Stage95方式で隔離copy・独立SQL/SHA/read-only閲覧一致を確認した。その読取証拠からさらに新規isolated-workを作り、元fixtureから複製したbaseline-workと同条件で実LiveGameService.load_gameを実行する。原本・候補・隔離証拠へload/replay/syncを呼ばない。両workは独立rootにあり、元slot identityを保ったまま新規作成する。既存save rootへの復元・登録・切替はない。

Linux/Python3.12.14/SQLite3.53.1で専用20件すべて成功、skip 0、360.927秒。6状態×2系列の全SQL・得点/inning/個人成績・roster/player identity・封印ledger/outcomes・manual/autosave checkpoint・runtimeが一致し、最終checkpointの再ロードと2回syncも冪等だった。実測は[continuation_linux_20261013.json](../../audits/phase2/stage43g96/continuation_linux_20261013.json)。65件の拒否・安全なwork内例外を検証した。うちload前拒否はload呼出し0件をassertし、load後故障は元・候補・読取証拠への変更0をassertする。全6状態で保護入力のfile集合/SHA不変、workだけが変化した。

|状態|選択|初回replay/系列|続行/系列|最終試合|年度台帳|baseline秒|isolated秒|各work bytes|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|active|manual|6|1|7|1|4.099094|4.027942|1607262|
|active|autosave|6|1|7|1|4.184397|4.090306|1607262|
|sealed|manual|7|0|7|1|4.154453|4.135226|3691326|
|sealed|autosave|7|0|7|1|4.061830|3.998730|3691326|
|registered|manual|7|0|7|2|4.062365|4.005803|3691326|
|registered|autosave|7|0|7|2|4.238658|4.056085|3691326|

最終再ロードは各系列7試合をさらに実replayした。activeの元slotは1393452 bytes、candidate/evidenceは9080519–9080523 bytes。sealed/registeredの元slotは3691326 bytes、candidate/evidenceは11379146–11379150 bytes。copy後のcandidate/evidence全byte一致を維持した。全同時fixture・FS割当・journal・メモリを含むピーク容量や性能SLOではなく、固定閾値はない。

sealed/registeredは2026 checkpointの再ロードと安全な年末境界を検証する。登録のみの2027は実ゲームcheckpointがなく、2027へのadvance拒否を要求する。翌年登録を翌年実ゲーム進行と数えない。scopeはactive/sealed/registered×manual/autosaveの6状態・各2系列で、全国100/200年連続実ゲームや全career、別PC replayの証明ではない。

20専用テストは保護入力改変、出典/互換/版/slot/source違い、receipt欠落、履歴先行、台帳/封印/outcomes/過年度roster欠落、career/feeder/資格/rulebook/v2、WAL/tmp/links、copy ENOSPC/EIO/interrupt、busy/read-only DB、非決定的replay、実子process中断、checkpoint公開失敗等を対象とする。未確認時はload前拒否、再ロード後障害はworkだけに限定する。改変注入ケースでは注入後開始時からハーネスが入力に書き戻さないことを確認する。

今回の開始時・最終照合時CSVは106件で集合/byte不変、既存save関連fileは0件だった。[保護結果](../../audits/phase2/stage43g96/protected_inputs_20261013.json)に件数と一致だけを記録した。既存4件の不変性・内容・再開は未検証であり、前段の存在件数を流用しない。private path/SHA一覧は公開しない。ユーザー実saveを試験入力にした件数は0。

## 回帰とCI

今回のLinux実行はStage91 20件、Stage92 21件、Stage93 29件、Stage94 38件、Stage95 20件、年次37件すべて成功・skip 0。関東8都県17校E2Eは2件成功・skip 0、773.348秒。[ローカル集計](../../audits/phase2/stage43g96/local_validation_20261013.json)に実測を記録した。

全Python初回実行は2182件、1541.199秒、skip 41、errors 1だった。実行開始時にimportされた修正前guardがOracleRefusedを固定BackupRefusedに変換していなかったため、新規台帳不整合拒否テストが期待した例外型と違った。ゲームは起動せず拒否しており、修正後の新規20件全体はskipなし成功した。初回全Pythonを単発成功と表示しない。最終headのPython3.12全unittestと関東専用CIで再確認する。ローカルTkは仮想displayが無く未実行で、Linux/Windows専用CIの実Tk15件で補完する。両OS・全CIの確定結果はPR Checksと本報告への追記に記録する。

生成時の外部版と出典を知っている自己生成process内に保証を限定する。receiptの署名/真正性/完全性、永続承認anchor、共通writer排他、各DB間原子性、実電源断・NFS・Windows実稼働rename・最終観測後の改変は未保証。[ADR-034](../adr/ADR-034-fixture-replay-production-restore-boundary.md)はProposed・未採用。保存年数制限を追加せず、旧A ISOと架空v2 G年を混用しない。本番復元承認・全ゲーム再開証明はfalseのまま。

PRはCI確認後もマージしない。auto-mergeを有効にせず、レビュー待ちで停止する。
