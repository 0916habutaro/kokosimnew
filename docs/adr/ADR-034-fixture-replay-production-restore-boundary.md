# ADR-034：fixtureの再ロード証明と将来の製品復元出典を分離する

- 状態：**Proposed／未採用**
- 日付：2026-10-13
- Issue：#247、Stage43G-96
- 関連：[ADR-033](ADR-033-manual-independent-backup-adoption.md)、[設計](../research/stage43g96_isolated_continuation_design_20261013.md)

現行live JSONには生成時の外部入力hashとslot IDが無く、export時の固定互換catalogは過去生成時の版を証明しない。unsigned receiptを再計算可能な者による整合的な履歴切落としもreceiptだけでは排除できない。Stage96のprivate anchorと生成過程の知識は一時process内の自己生成fixtureに限られ、外部候補への恒久承認として転用できない。

選択肢は、(1)現契約のまま本番restoreを未導入とし手動export/verifyを継続、(2)将来の保存生成時に互換入力版・明示slot出典を保持し旧saveの未知版を別審査、(3)別途承認した信頼anchor/署名・複数DB公開境界・writer排他の設計を採用してから製品restoreを検討すること。今回採用する製品変更はない。署名があってもruntime/career依存の再開試験を省略できない。

次Stageはこの限定実験のCI・状態範囲をレビューし、拡張fixture検証と生成時互換証拠の保存契約を別々に判断する。本番save復元、既存slot登録・切替、自動restore、schema移行、履歴GC、GUIは承認済みと扱わない。ADR-033のAccepted範囲は手動exportに限ったまま維持する。
