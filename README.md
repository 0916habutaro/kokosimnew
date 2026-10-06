# KokoSimNew / ココシミュNew

高校野球の大会構造・日程・試合進行を扱うゲーム用データ／エンジンの管理リポジトリ。

## 現在地
- Phase 1: 完了（47都道府県、学校 3,746、硬式野球部 3,746）
- Phase 2: Stage 12Kまで統合中（県大会Stage 12I・地区大会Stage 12Jを追跡しつつ、全国大会カレンダー／依存関係を監査）
- Stage 12G: 全国47都道府県の春秋94大会の日程を `season_calendar.csv` に正式反映済み
- 県春秋94大会の日程: official_schedule 94 / research_pending 0
- Stage 12G初回試合日: 累計809日。Stage 12I再照合で福岡秋10/14を追加し、現在のmasterは810日相当

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
python -m phase2_engine.reconciliation_cli \
  --queue audits/phase2/stage12i/stage12i_autumn_reconciliation_queue_20261006.csv \
  --as-of 2026-10-06 \
  --output audits/phase2/stage12i/stage12i_recheck_status_20261006.csv
```

## 正本ルール
展開済みの `data/`, `phase2_engine/`, `tests/` を正本とする。`archive/snapshots/` のZIPは復旧用で、日常編集には使用しない。

## 次工程
Stage 12Kで全国3大会を監査。選抜11試合日・夏甲子園15試合日と各抽選日をmasterへ補完し、神宮は10/17抽選待ちとしてgame_date_listを未確定のまま保持。全国出場依存は選抜32・夏49・神宮10の構造を監査する。
