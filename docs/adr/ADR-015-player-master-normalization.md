# ADR-015: 選手プロフィールはGameStatsと分離したplayer_masterを正本にする

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 13D-1のGameStatsにはplayer_idとschool_idだけが保存されている。

GUIで選手名・学年・守備位置を表示するため、GameStats各rowへプロフィールを複製する方法もある。

しかし同じ選手は複数試合・複数大会で多数rowを持つため、表示名修正や将来のプロフィール拡張時に重複更新が発生する。

## Decision

SQLite schema v3へplayer_masterを追加し、選手プロフィールはyear + player_idで1行保存する。

GameStatsはplayer_idだけを参照し、read時にjoinする。

school_nameもplayer_masterへ重複保存せずschool_recordsからjoinする。

## Consequences

- player profileの正本が1か所になる
- GameStats tableを小さく維持できる
- 選手名変更・正式name provider導入時もmaster更新だけでよい
- 古いGameStatsのみのfixtureではmasterがないため、read modelはplayer_id fallbackを許容する
