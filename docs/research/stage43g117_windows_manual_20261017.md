# Stage43G-117 個人Windows PC手動確認手順

個人PCでの目視・サインアウト／再ログイン・OS再起動は**未検証**。hosted CIの成功とは別扱いにする。
既存のsave・backup・slotは指定しない。Windows Python3.12と、Git履歴を持つ指定ブランチのcheckoutで実施する。

1. PowerShellで `python tests/stage43g117_audit.py --require-windows --json-output stage117-pc-new.json` を実行する。
   reportには未作成の名前を使う。試験は自己所有の一時領域に新規DBを作るだけで、既存saveは読まない。
2. `successful=true`、`tests=16`、`skipped=0`、`failures/errors=0`、`native_windows=true` を確認する。
3. `measured.fixture` で保存2026=31、2027学校=33、練習=1、Stage116 v1=2 を確認する。
4. `measured.tournament.games` の7試合（1回戦4・準決勝2・決勝1）について、得点・イニング・投打row数・oracleを確認する。
   2回戦以降の対戦teamが前ラウンドの勝者だけであること、namespaceが `fictional:` であること、
   公式情報がNone／falseであることも確認する。
5. `measured.tournament.joint_school_standalone_records` で、合同の構成2校が単独0勝0敗であることを確認する。
6. `measured.restart` で次の状態を確認する。
   - 試合1・4・6・7のcommit直後にprocessを強制終了し、各再開時点の保存試合数が0→1→4→6、最後が7になっている。
   - 未完了の段階では優勝・順位がnull／空。
   - 完了後は8team分の順位と架空優勝がある。
7. close→rename→reopen、junction／hardlink／sidecar／hot journal／lease拒否の全caseがskipなしで成功したことを確認する。
8. PCをサインアウト→再ログインし、別の新しいreport名で1–7を再実施する。必要ならOS再起動後にも再実施する。
   これは一時fixtureの終了後の永続復旧を保証する試験ではない。日時・Python/SQLite・結果を報告書へ追記する。

この試験は2027公式の参加・資格・合同継続・日程・順位を確定しない。製品slotへの統合や復元操作も行わない。
