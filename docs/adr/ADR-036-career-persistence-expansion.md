# ADR-036: 初年度保存契約から全国・年次保存へ広げる条件

Status: **Proposed（未採用）**

Date: 2026-10-14

Stage43G-100は既知8校2026年MAIN単大会だけを明示契約として接続した。Stage99のADR-035で提案した保存責任の一部を実装したが、全国／他年度・replay互換の承認には広げていない。

次Stageでは、複数大会に共通する学校年度rosterの所有者と生成seed、年次advance後のimmutable出典、pre-MAINで能力resolverが使う全学校集合、feeder／qualifierの結果確定タイミングを定義する。cacheの列挙や学校名によるID補完を全国入力の正本と扱わない。認可scopeを増やす前に、完全Aと選手ID／所属・大会結果・年度台帳を独立oracleで一致させる。

複数DB／JSONのcommitは現時点で非原子的。将来journal／共通transaction／外部排他を選ぶ場合は、各停止境界で元checkpoint・封印記録を保全する仕様とread-only診断を先に確定する。任意の破損／欠落を自動修復するものとは扱わない。

catalogの次版は真の変更前候補を準備してから更新する。旧known digestは候補内容verify用で、replayの許可リストではない。旧code常設同梱、既存save migration／restore、履歴削除、全国GUIの一括導入は採用しない。

Windows Python3.12で正常・異常・rollback・generator中断・mapped Tk子窓終了後のnative closeとrenameを必須にし、全unittest・関東17校・旧候補回帰を維持する。人の個人PC目視・操作とCI自動操作は別の証拠として報告する。
