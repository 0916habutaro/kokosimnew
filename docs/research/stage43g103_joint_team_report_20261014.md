# Stage43G-103 合同チーム分離の限定検証報告

Issue #261、最新main `8480dc0`から専用ブランチ `stage43g-103-joint-team`。詳細は[日本語設計](stage43g103_joint_team_design_20261014.md)、次工程案は[ADR-037 Proposed](../adr/ADR-037-competition-team-school-separation.md)。

## 結論と採用範囲

公式出場一覧の**全32行**を学校masterと照合した。農林・塩山合同1枠＋単独31枠が33学校に対応し、対応上の追加／不足0。学校202農林・220塩山は別々のまま保持する。公式の資格審査・seed・個別枠／試合日・登録選手数規則を認定したものではなく、実結果や実選手は採取しない。

**合同writerは採用しない。32チーム・31試合への拡張は未実施。** エンジンの学校master gate、SchoolRosterの学校／番号検証、能力生成のone-school条件、完全Aの学校=対戦側ID、学校順位とread-only集計が障害になる。所属をteam_idへ書換える方法は永久identityを損なうため実装しない。Issueの縮小条件に従い、read-onlyチーム構造と小規模adapter preview、拒否回帰までを完成した。

小規模fixtureは4校80人／3出場チーム（農林＋塩山合同、帝京第三、北杜）。年大会namespace `FX103:2026:CMP000041:*` に所属学校集合を保持する。架空ロスターseed430103を試合seedと混同せず、元学校ロスターを組込みrecipeと再照合する。合同の20人はposition枠ごとの学校交互選抜で10人ずつの**試験用プレビュー**。40人同時登録や公式登録規則ではなく、元の永久ID・所属・入学年・学年・roster_noは不変。

大会チームIDを学校masterへ追加せず、ゲームwriterへの変換は明示例外で拒否する。学校の二重出場、team ID衝突、ID改変、所属付替え、学年／入学年／seed改変、正本不足・重複、未知年度・構成変化も拒否。合同解散後の試合史保存やteam順位は未実装で、previewからスコアや優勝・単独学校成績を補完しない。

## 実検証と互換性

Linux補助Python3.12.14で専用headless10件21.063秒、native mapped Tk1件0.500秒が成功、双方skip0（aggregate JSONをaudits/phase2/stage43g103に保存）。Tkは3枠の選択→元学校ID／永久ID／学年／入学年を全20人表示し、callback例外なし、DB bytes不変を確認。製品head `7da5dc4` の[専用Windows CI](https://github.com/0916habutaro/kokosimnew/actions/runs/38583924232)でもPython3.12.10 headless10件・native mapped Tk1件が両方成功・skip0。Tkは1.884秒。最終head全CIはPRの実行結果で確認する。

|実施した検証|実際の証明範囲|
|---|---|
|read-only合同3枠の出典・選抜|4校80人正本、合同20人、ID／学校不変、可変返却値からの切離し|
|実TournamentEngine|合同namespaceを学校入力に渡すとMAIN作成前に拒否。合同試合実行0件|
|実AbilityMatchResolver／TeamStrengthGenerator|混在学校ロスターと能力inputを拒否。ID所属の再ラベルなし|
|学校正本raw SQL／JSON／SHA|4校80永久IDを独立recipeで照合、学校／identity索引とpayload一致|
|従来の実試合baseline|既存Stage101の2大会6実試合を実エンジンで保存・封印。独立SQL/SHAでスコア・イニング・チーム／投打成績・順位を照合し、read-only試合／6校／120永久ID全履歴と比較|
|native SQLite lifetime|接続を保持したまま製品closeをassert。DB rename→reopen→integrity_check、閲覧bytes不変|
|旧5版候補|真の94/99/100/101/102 Git checkout、別Pythonプロセスで自己生成export/verify、変更後read-only内容verify・候補bytes不変|
|保存互換|338catalog全入力bytes不変、106master CSVとdata全集合／bytes不変。Stage100–102保存契約と既存8校demo／33校Tkを変更しない|

catalog編集前の真のStage102 main旧候補も別プロセスexport/verify済み。今回catalog対象ソースの編集は0、catalog版更新0。94–101の現行replayは従来通り拒否。102のruntime入力版は同一で、合同replayを新たに許可したのではない。候補内容健全性は真正性証明・本番restore認可ではない。

新専用Windows Python3.12 headless10件・native mapped Tk1件をzero skips CI gateとして追加。既存Stage94–102・Windows SQLite/Tk・全Python・関東17校E2Eは維持し、skip追加や失敗黙殺をしない。Linux関東17校E2Eは2件415.354秒、skip0で成功。Linux全unittestは実行中で、完了結果と最終head CI結果をPRに記録する。個人Windows PCでの目視・手操作は未検証。所定既存save rootの候補0件、内容検証・試験入力利用0。

## 残る設計と停止条件

必要な次工程は、年大会team台帳・学校membership・20人登録簿、元学校とteamを分ける能力／完全A入力、新reader／学校参加index／team順位／leaderboard契約を先行実装し、旧5版verifyとSQL独立oracleを成立させてから限定writerを採用すること。小規模実2試合の完全Aと元学校履歴、BYE・勝上り・未完了seal・途中commit故障を証明して初めて32枠31試合へ進める。

現時点のJSON／複数SQLite保存は非原子的。新schema・migration・既存save変更・本番restore/import/activation・履歴削除・合同資格の全国接続・翌年開始・EXE配布は追加していない。Stage102の33校32試合成功と合同32チーム31試合完了を区別する。

最終headの全必須CI成功を確認しても、PRはマージせずauto-merge無効でレビュー待ちに停止する。
