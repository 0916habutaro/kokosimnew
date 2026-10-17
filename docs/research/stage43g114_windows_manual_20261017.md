# Stage43G-114 試験用CLI手動確認

Windows Python3.12、repository rootで実行する。既存save/backup/任意SQLiteは指定できない。
全データは新規TemporaryDirectory内の自己生成試験用で、終了時に所有者が片付ける。製品slotへの永続保存機能ではない。

```powershell
$env:PYTHONUTF8 = '1'
python examples/stage43g114_practice_history.py --self-created-only --player-state returning
python examples/stage43g114_practice_history.py --self-created-only --player-state newcomer
```

各コマンドは保存2026山梨31試合を実生成・検証し、別SQLiteへ2027の全33校ロスターを保存・受理した後、
保存JSONから単独2校の実1試合を計算・別SQLiteへ保存する。全storeを明示closeして別processで再開・oracle照合する。
2コマンドは独立した自己生成試験であり、ユーザーの以前のゲームを再開する操作ではない。

表示の確認：

1. `schools` の2026 `fictional_tournament` と2027 `fictional_practice` を区別し、得点と全イニングを見る。
2. returningでは同じ永久player_id・元学校・入学年のまま2026/2027の投打実登場成績が表示され、学年だけ進級する。
3. newcomerではtransition=newcomer、entry_year=2027、2026はnot_yet_enrolled/登場なし、2027に初試合成績がある。
4. 公式2027資格・日程・順位はNone/未確定であり、練習試合勝敗から公式戦績が作られていない。
5. エラーを実1試合成功と読み替えず、コマンド終了コードと例外を確認する。

専用自動audit（出力先は新規ファイル。既存ファイルを上書きしない）：

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tests/stage43g114_audit.py --require-windows --json-output work/practice2027-manual.json
```

個人PCでの目視、サインアウト→再ログイン、PC再起動は今回のhosted CIとは別の実証項目。
必要時は再ログイン/再起動後に同じCLIを再実行し、環境・終了結果・表示確認を記録する。
これは新規fixtureの再実行であり、OS再起動を跨いで一時storeが保存されるという主張ではない。
