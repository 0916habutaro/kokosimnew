# ADR-031：世代backup/restoreの公開条件と正本・派生分離（評価提案）

- 状態：**Proposed / 未採用。production導入・schema変更・移行・削除の承認なし**
- 日付：2026-10-12（日本時間）
- Stage：43G-90 / Issue #235
- 前提：[ADR-030](ADR-030-v2-multifile-generation-snapshot-proposal.md)。本ADRはADR-030をAcceptedへ変更しない。

## 背景と実験で分かった制約

v2のappend/sealは同一DB内で直列化済みだが、calendar・v2・ロスター・独立学校索引の全体世代transactionはない。旧Aのlive JSON/replayとarchive再同期は別経路で、新v2世代復旧の保証として流用できない。

実験ではcommit済み未checkpoint WALをSQLite backupで回収できる一方、DB毎backupの間に次年度を保存すると同一世代集合として拒否された。学校索引metaは原本/calendar絶対pathを保持し、新規復元dirへコピーした索引はforeign出典で拒否された。file SHAを書換えたmanifestだけでは世代/信頼元を証明できない。

## 提案する判断（まだ決定ではない）

slot/generation単位の必須正本集合を先に承認する。全封印履歴完全A、calendar、ledger、ロスター/identityと、製品の場合はlive replay JSONと互換依存を優先する。学校/選手索引は不使用から始め、別操作で新規生成・出典検証・明示候補承認する案を推奨候補とする。旧索引metaを復元先へ書き換える移行は採用しない。

成功結果は全旧世代・全新世代のみとし、active/欠落/世代ずれ/foreign/信頼元不明は明示拒否する。SHAは内容照合であって署名ではない。永続approval anchor、署名/鍵/ローカル所有権の信頼設計は未決定。

immutable世代＋manifest、共通lock、SQLite backup、ATTACHの4方式は[設計比較表](../research/stage43g90_generation_recovery_design_20261012.md)に記載。実測は私有fixtureのimmutableコピー＋SQLite backupだけで、製品案を選定したものではない。共通lockは参加者の集合固定とcrash後の公開を分けて設計し、ATTACHはWALのmulti-DB crash atomic性を保証しない制約を受ける。

## 承認前に残る判断

- 製品の対象機能、正本依存の全inventory、旧A/live JSONとv2の運用接続・移行要否。
- 世代identity/公開参照、同FSのno-clobber公開、reader pin、Windows handleとLinux directory fsync、電源断検証。
- 長期backupのbusy/retry/timeout、32シャード超の再生成batch、未封印live途中状態をどの機能で公開できるか。
- 永続承認の原子性、外部backupの署名と鍵/信頼元、復旧候補inventory/不使用索引のUX。
- 年数無制限のまま世代保持数・容量ピーク・最終正常世代pin・利用者が承認するGC候補。歴史のOption Aを削除しない。

## 今回の実装境界

自分で生成したTemporaryDirectoryだけのtest/測定CLI、raw独立oracle、process.kill/WAL/改ざん/衝突テスト、両OS小規模CIを追加する。production保存API・GUI・schemaを変更せず、既存saveを入力/出力にする復元/上書き/削除機能は作らない。署名、共通lock、ATTACH、製品manifest、migration、自動restore/promotion/索引承認は実装しない。

実験のメモリ上approvalを製品の永続信頼源と見なさない。プロセスkillはOS電源断の証明ではない。実ディスク満杯は再現せずENOSPCを境界注入する。報告の容量は合成fixtureで、全国100/200年の連続大会進行ではない。実測値を復旧SLOや耐久性保証に変換しない。

PRをマージしない。次Stageの採用・移行・schema変更・削除・本番導入にはユーザーの明示承認が必要。
