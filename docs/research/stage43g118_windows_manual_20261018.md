# Stage43G-118 個人Windows PC手動確認手順

個人PCでの目視・サインアウト／再ログイン・OS再起動は**未検証**。hosted CIの成功とは別扱いにする。
既存のsave・backup・slotは指定しない。Windows Python3.12と、Git履歴を持つ指定ブランチのcheckoutで実施する
（旧20版RO候補の自己生成に `git archive` を使うため、浅いcloneでは実施できない）。

1. PowerShellで `python tests/stage43g118_audit.py --require-windows --old-versions --json-output stage118-pc-new.json` を実行する。
   reportには未作成の名前を使う。試験は自己所有の一時領域に新規DBを作るだけで、既存saveは読まない。
   hosted Windowsでの所要時間は報告書を参照（PCの性能で大きく変わる）。
2. `successful=true`、`tests=13`、`skipped=0`、`failures/errors=0`、`native_windows=true`、
   `old_versions.file_count=20`・`old_versions.skipped=0` を確認する。
3. `measured.fixture.parts` で、保存2026全31試合→2027受理33校→練習1→Stage116 v1 2→Stage117 7の各時間を確認する。
4. `measured.thirty_two.games` の31試合（1回戦16・2回戦8・準々決勝4・準決勝2・決勝1）について、得点・イニング・投打・oracleを確認する。
   `measured.thirty_two.ranks` が1・2・3・3・5×4・9×8・17×16の32件であること、namespaceが `fictional:` であることを確認する。
5. `measured.thirty_two_run` で、試合1・16・24・28・30・31のcommit直後の強制終了と、各子processの開始時の保存試合数
   0→1→16→24→28→30（`child_start_states`）、未完了時の優勝null・順位なしを確認する。`per_game_seconds` と
   `db_bytes_after_game` で1試合ごとの時間・容量の増え方を見る。
6. `measured.sixteen` で16team／15試合（1・8・12・14・15で強制終了）の順位と再開を確認する。
7. `measured.history.joint_schools` で、SCH000202・SCH000220が全scenarioで単独0勝0敗、合同entryの記録だけを持つことを確認する。
8. PCをサインアウト→再ログインし、別の新しいreport名で1–7を再実施する。必要ならOS再起動後にも再実施する。
   これは一時fixtureの終了後の永続復旧を保証する試験ではない。日時・Python/SQLite・結果を報告書へ追記する。

この試験は2027公式の参加・資格・合同継続・日程・シード・組合せ・順位を確定しない。製品slotへの統合や復元操作も行わない。
