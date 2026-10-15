# ADR-041: 32出場teamと33学校正本を分離した段階実行lab

- Status: **Proposed（製品未採用）**
- Date: 2026-10-15
- Context: Stage43G-108 / Issue #271。ADR-037–040を継続。

既存の4校／3team／2試合契約を書換えず、専用namespaceと登録・plan・match入力型、厳密validator、独立bracket oracleを追加する。学校正本660人と出場登録640枠を別台帳にし、合同は1枠、永久IDと元学校は不変とする。公式出場32行の照合は利用するが、対戦・日付・選手・勝敗は架空である。

登録と31枠dry-run、合同入り8team7試合、32team31試合を順に受入する。新SQLiteは親所有TemporaryDirectory限定、各試合append-only transaction、別spawnプロセスへ明示capabilityを渡して再検証後に継続する。順位は敗退roundごとの同順位。学校参加とteam勝敗を分け、readonly履歴Tkを製品へ接続しない。

旧338catalog・106CSV・製品writer/schemaと旧10版RO互換を維持する。単一SQLiteの試合単位原子性だけを実証し、製品restore・移行・永久保存・全国一般化・2027進行を認可しない。ADR-037–040もProposedのまま。
