# KokoSimNew / ココシミュNew

高校野球の大会構造・日程・試合進行を扱うゲーム用データ／エンジンの管理リポジトリ。

## 現在地
- Phase 1: 完了（47都道府県、学校 3,746、硬式野球部 3,746）
- Phase 2: Stage 12Fまでの大会構造・共通エンジンを統合済み
- Stage 12G: 東北6県の春秋12県大会日程を `season_calendar.csv` に正式反映済み
- 県春秋94大会の日程: official_schedule 15 / research_pending 79
- 東北12大会の試合日: 92日レコード

## ディレクトリ
- `data/master/` 学校・加盟校・出典の基礎マスター
- `data/areas/` 地区区分・学校所属
- `data/competitions/` 大会・stage・進出・seed・format・地域大会接続
- `data/schedules/2026/` 2026年日程マスター／試合日
- `data/sources/` Phase 2調査出典
- `phase2_engine/` 大会・シーズン共通エンジン
- `tests/` 回帰テスト
- `audits/` Phase/Stage別の監査・manifest・validation
- `archive/snapshots/` 移管元の完成ZIP（復旧用）

## 実行
```bash
python -m unittest discover -s tests -v
python -m phase2_engine.season_cli --data-dir data --year 2026 --seed 2026100501
```

## 正本ルール
展開済みの `data/`, `phase2_engine/`, `tests/` を正本とする。`archive/snapshots/` のZIPは復旧用で、日常編集には使用しない。

## 次工程
Stage 12G 関東（東京を除く県）の春秋大会日程を同じ形式で追加する。
