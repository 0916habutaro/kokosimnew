# Stage43G-108 実装・実測報告

Issue #271。PR #270マージ済みmain `a657960afbf00d3fbd2f7c091532a0ba647347a2`から専用ブランチで実装。[設計書](stage43g108_yamanashi32_design_20261015.md)と[ADR-041 Proposed](../adr/ADR-041-yamanashi32-staged-tournament-lab.md)参照。

## 実装範囲

新しい独立labの登録・8/32team plan・match入力・独立bracket oracle・隔離SQLite・readonly履歴Tkを追加。旧Stage100–107 API・338catalog・106CSV・製品save/writer/schemaを変更していない。33校660永久ID、32team640登録、合同10＋10選抜と未選抜20人保持、5ラウンド31枠のGate AはLinux補助4 tests/skip0で成功した。

ゲーム内ブラケットseed430108と固有試合seedによる架空大会。2026公式大会の組合せ・シード・個別日程・実選手・結果を再現したとは主張しない。20人登録と10＋10比率はゲーム用仮定。旧確率の部分利用・確定進塁・犠打/失策/盗塁等未対応、疲労/怪我未接続のStage105 labモデルを継続する。

## 実測とCI

Gate B/Cと故障・旧10版候補・全unittest・関東17校E2E・Windows headless/native Tkの結果は検証完了後に本節へ追記する。未実施／失敗を成功と扱わない。専用CIは19 headless / 1 native mapped Tk、skip0を必須にする。個人Windows PCで人が触った目視手操作は未検証。

## 保護境界と残課題

原子性は単一SQLite内の試合transactionのみ。31試合全体やJSON/複数製品DBの同時原子性は保証しない。SHAは整合性確認で真正性署名ではない。親所有TemporaryDirectory終了後の製品長期保存は未対応。合同の勝敗/優勝を構成校の単独成績に複製しない。

既存save利用/変更、本番restore/import/activation、履歴削除/GC、製品writer/schema採用、2027実開始、全国一般化、正式全国GUI一括実装、EXE配布を行わない。ADR-037–041はProposed・製品未採用。旧候補生成の重複整理は別Stageでfixture独立性を確認してからとし、今回は既存保障を維持する。

最終head全必須CI成功後も未マージ・auto-merge無効でレビュー待ち。
