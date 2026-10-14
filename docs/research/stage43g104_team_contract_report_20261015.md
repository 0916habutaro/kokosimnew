# Stage43G-104 実装・検証報告

Issue #263。Stage103を含む最新mainから`stage43g104-team-registration`を作成。Windows専用・個人利用・非配布の限定実装。

## 成果と停止判断

- 4校80人の学校正本を保持し、3出場チーム・60登録枠を新しいimmutable台帳に分離。農林・塩山合同は20人（各10人）という自己生成の検証規則。永久ID、元学校、入学年、学年、元roster_no、positionを不変参照する。
- 年・大会・team namespace、recipe/version、各学校正本SHAと集合SHA、team_slot、学校参加の読取索引を持つ。名前をjoinに使わず、同名別永久IDを別人として検証する。
- 明示opt-inの新入力型・validatorを実装。能力は元学校・入学年の既存SchoolAwarePlayerAbilityGeneratorで生成。学校能力seedと試合seed、登録簿recipe、起用recipeを分ける。labの平均能力と打順／投手順は既存TeamStrengthや確率モデルに採用した値ではない。打順のPと投手起用順の先頭は一致させ、先発関係をoracleで検証する。
- 別の読取Tkで3チーム→構成校→元学校／永久ID／学年／入学年／登録番号を表示。試合結果は未対応と明示し、参照失敗時は前表示を消して拒否する。既存8校・33校GUIへ合同結果を混入させない。
- **合同実試合0件**。新入力が成立しても、旧simulateは個人成績school_idへ対戦側IDを渡す。完全Aの新result/event/stat型、team辞書を使うdriver、元学校検証と独立再集計が未成立。無理なadapter・school_id置換・validator緩和を実装せず、専用例外で旧変換と試合入口を拒否した。
- BYE／勝上り／3チーム2試合／山梨32チーム31試合は未実施。製品writer・HistoricalMatchArchive・CareerCompetitionOutcomesの保存schemaと338入力catalogを変更していない。ADR-037および追加ADR-038はProposed・未採用。

## 検証と受入

新headless gateは14テスト、skip 0（登録／入力11、真のStage103候補1、旧5版候補2）。初回補助Linux計測は28.661秒。登録簿のoracleはTemporaryDirectoryのCareerRosterArchiveを独立SQLで読み、全4校80人のJSON・永久identity・SHA、全3membership・60登録枠を照合。公式結果・公式選抜人数・公式seedの再現を主張しない。

拒否検証は二重学校membership、未所属、異年度、source/recipe版、改ざんseed、重複永久ID、欠落ロスター／登録、学校team ID衝突、元学校／position／学年／入学年／登録番号／SHA／能力／打順／投手順／平均値の改ざんを含む。boolとintの同値比較でも型不一致を拒否。旧simulatorが一度も呼ばれないこと、単独学校能力とStage103プレビューが変わらないことを検証した。

真のStage94/99/100/101/102/103の6checkoutから独立プロセスで自己生成模擬旧候補をexportし、read-only内容verify、候補bytes不変を確認。338catalog入力bytesと106master CSVを含むdata全bytesは変更なし。旧94–101の再生は拒否維持、102/103は製品コード版不変で追加の再生認可ではない。verifyは真正性署名・本番restore認可ではない。

Windows既存joint preview workflowに新headless14件とnative mapped Tk1件のzero skips gateを追加。既存Stage103のheadless10件／Tk1件も維持し、Stage91–96の6workflowへStage104 pathsを加えた。既存Stage100–103保存／閲覧、旧互換、Windows SQLite接続解放、全Python unittest、関東8都県17校E2Eも維持。最終CI結果は本PRのChecksに記録する。個人Windows実機の目視／手操作は未検証。

## 次Stageに必要な最小改修と保全

[設計書](stage43g104_team_contract_design_20261015.md)の契約表と[ADR-038](../adr/ADR-038-registered-team-full-a-lab.md)に、新完全A型、確率計算の副作用のない再利用境界、新driver、版判別reader、新保存型、学校参加index、rollbackを具体化した。これらの製品採用には別Stageのレビューが必要。

既存セーブを試験入力として使わず、本番restore/import/activation、既存slot上書き、自動移行、履歴GC/削除、全国合同一般許可、翌年開始、配布機能を実施していない。試験用DBは自己生成TemporaryDirectoryだけ。JSON／複数SQLiteの非原子性を改善したとは主張しない。公開artifactは集計だけで、候補内容・秘密・絶対path・個別digestを含まない。

全必須CI成功後もPRをマージせず、auto-merge無効のレビュー待ちで停止する。
