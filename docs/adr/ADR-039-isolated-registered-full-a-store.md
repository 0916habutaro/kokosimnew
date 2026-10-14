# ADR-039: 登録チーム完全Aの隔離append-only SQLiteと検証読取

- Status: **Proposed（製品未採用）**
- Date: 2026-10-15
- Context: Issue #267 / Stage43G-106、ADR-037/038を継続

Stage105で生成した2026合同1試合の完全Aを、自己所有TemporaryDirectoryに専用SQLiteとして保存する実験を追加する。大会team・membership・登録選手/元学校・固定ロスター出典・入力・結果・学校参加索引を同一transactionに入れる。旧school-keyed archiveや製品saveには接続しない。

読取は版判別、exact schema、canonical正本/SHA、独立event oracle、同seed再計算、membership由来SQL索引を検証する。UPDATE/DELETEはtriggerでも拒否し、同一再保存のみ冪等、異内容競合は拒否。全接続は明示close。hot journalの復旧はread-only readerの責務にしない。

学校履歴は合同参加を示すだけで合同勝敗を各校単独成績へ転記しない。永久選手の元学校と当時teamは全件保持する。旧無版Aの識別は新oracleによる旧試合認証を意味せず、旧readerの互換検証経路を保つ。

このADRは製品writer/schema変更、restore/import/activation、全国合同進行、翌年度開始、真正性署名、長期全打席保存、JSON/複数DB原子性を認可しない。今回の実証範囲は2026固定自己生成1試合とnative Windows CIまで。
