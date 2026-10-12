# ADR-030：v2複数SQLiteの保存世代snapshot（提案・未採用）

2026-10-12。Stage43G-89 / Issue #233。状態：**提案のみ。実装・移行・承認なし**。

## 判断を必要とする条件

現在のreaderは独立したread snapshot、ledger/SHA/出典照合、観測したcommit/renameの拒否を提供する。append-only calendar/封印済み年度では過去の正しいprojectionが返るかactive/staleを拒否するが、全ファイルの同一世代や最新状態は保証しない。外部backup/restore、複数slotの同時切替、世代単位の公開・障害復旧を要求すると、writer全体と保存形式の契約変更が必要になる。

Stage89では同一v2ファイルのappend/sealにBEGIN IMMEDIATEを追加した。このSQLite writer予約は共通永続lock導入ではなく、複数DB世代設計を承認したものでもない。

## 比較する案

| 案 | 期待する効果 | 移行・制約・未決事項 |
|---|---|---|
| immutable世代ディレクトリ＋manifestを最後にatomic公開 | readerが1つのmanifestでsource/calendar/indexの世代・SHAを選び、旧世代を閲覧可能 | 全writer/backup/復旧の公開契約、manifest署名/信頼元、既存saveの参照方式、世代保持容量、GC承認が必要 |
| slot共通ロック | 全writerとreaderのsnapshot確保/公開を協調 | 全経路に参加を義務化。プロセス・OS・crash・NFS・lock timeoutを決定。raw書換え/外部restoreは別契約 |
| SQLite backupによるコピーsnapshot | 読取・exportを不変コピーへ分離 | 個別backupだけでは元の同一時点を保証しない。共通世代/ロックと併用。WAL安全性、容量ピーク・時間費用が必要 |
| ATTACHと共通transaction | SQLite内で複数DBを操作 | WALで複数DB一括crash atomic性は保証されない。journal mode変更、同期設定、独立索引の扱いと既存保存の移行を検討 |

候補の採用は別Stageで行う。manifest・lock・ATTACH・schema変更・sealedデータの書換えをStage89へ持ち込まない。

## 次Stageに必要な受入試験

- calendar→append→seal→索引→公開の各commit前後でkillし、再起動後に全旧世代/全新世代/明示拒否のいずれかだけを選ぶ。
- 2プロセス以上、WAL checkpoint、rename/restore、lock失効、disk full、target衝突、複数slot、旧save読取を試験する。
- sealed完全Aの最終スコア・イニング・個人成績、calendar/ledger/payload SHA、全学校所属検証を維持する。
- 全世代一致oracleを、readerやmanifest writerと独立した入力・raw SQL・hash照合で構築する。世紀境界・30件・0件・複数大会を含む。
- 世代保持容量とbackup/公開時間を実測し、年数無制限と履歴非削除の方針を守る。100年度/索引・32シャード/操作の制限を保存年数上限へ変えない。
- 既存saveの参照/移行は明示承認し、旧AはISO日付のまま保護する。索引の独立手動承認・Tk試験GUIを維持する。
