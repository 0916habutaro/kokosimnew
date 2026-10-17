# Stage43G-116 個人Windows PC手動確認手順

個人PCでの目視・再ログイン・OS再起動は未検証。hosted CIの成功とは別扱いにする。
既存saveやbackupを指定せず、Windows Python3.12とGit履歴を持つ指定ブランチのcheckoutで実施する。

1. PowerShellで `python tests/stage43g116_audit.py --require-windows --json-output stage116-pc-new.json` を実行。
   reportは未作成名を使う。試験は自己所有一時領域だけに新規DBを作り、既存saveを読まない。
2. successful=true、tests=13、skipped=0、failure/error=0、native_windows=trueを確認。
3. measured.fixtureの保存2026=31／2027学校=33／練習=1、measured.tournamentの2試合について
   得点・イニング・投打row数・oracleを確認。表記が架空namespaceで、公式情報がNone／falseであることを確認。
4. measured.restartで1試合保存直後のprocess強制終了、matches=1／complete=false／champion=null／ranks=[]、
   別process後のmatches=2／complete=true／架空優勝を確認。合同teamの元学校2校と単独勝敗0を確認。
5. close→rename→reopen、junction/hardlink/sidecar/hot journal／lease拒否の全caseがskipなしで成功したことを確認。
6. PCサインアウト→再ログイン後、別の新規report名で1–5を再実施。必要ならOS再起動後にも再実施。
   一時fixtureの終了後永続復旧を保証する試験ではない。日時・Python/SQLite・結果を報告書へ追記する。

この試験は2027公式参加・資格・合同継続・日程・順位を確定しない。製品slotへの統合や復元操作を行わない。
