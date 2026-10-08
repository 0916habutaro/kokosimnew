# Stage 13E-3G-11：広島春季西部の選抜免除・予選枠の実行時監査

作業日：2026-10-09

## 根拠と問題

2026春季広島の西部地区は県大会7校、そのうち選抜出場の**崇徳**が予選免除で直接出場し、予選を勝ち抜く学校は6校。残り3地区は北部7・南部9・東部9で春季32校。

- 公式：https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会
- 2月28日地区予選方式：https://www.hb-nippon.com/articles/11302
- 4月14日出場校一覧：https://www.hb-nippon.com/articles/12440?page=2

旧設定では西部の`SGR000140`の`output_slots=7`を全て予選枠と解釈し、別途直接枠を追加すれば8校出場になる危険があった。また当該大会のAccess Rule自体が未登録だった。

## 修正

- `ACR000023`：選抜`CMP000001`の各年度参加校から広島所属校を抽出し、`quota_mode=all_matches`で直接MAINへ。学校名を埋め込まない。免除校は予選本体には参加しない。
- `PAR0347`：`SGR000140`のみ、地区の7枠が直接MAIN枠を**含む**と明示。
- `direct_access_quota.py`：所属地区の直接出場校数を名目枠から控除。1校なら6＋1=7、ゼロなら7＋0=7。別地区は控除しない。
- 既存一括実行`engine.py`、日付別lazy実行`premain_competition_runtime.py`の両方に同一処理を接続する。
- 回帰テスト：年間の直接出場数変動、地区間干渉防止、両エンジンのMAIN32校、資格免除校の予選排除。
- `hiroshima_qualification_missing_award_queue_2026.csv`：既存37試合に資格確定カードを結び付けられていない46校を学校・季節・地区単位で調査キューに保存。根拠なしで試合や確定日を捏造しない。

## 制限

既存の2026地区別公式PDF8件は全試合の本文照合未完了。46校の登録は**追加試合の取得完了ではなく残件の明文化**。`RS2026026` / FMT025（歴史上の任意順位戦）は依然`design_pending`。本件は資格計算と直接枠に関する修正であり、シミュレーションの学校名を実在の崇徳に固定しない。

## 検証方法

```bash
python -m unittest tests.test_stage13e3g11_hiroshima_direct_quota -v
python -m unittest discover -s tests -p 'test_*.py'
```
