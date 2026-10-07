# ADR-011: pre-MAINもMAINと同じMatchResolution境界を使う

- Status: Accepted
- Date: 2026-10-07

## Context

高校野球大会にはMAIN本戦以外にも、地区予選、seed決定戦、一次予選、リーグ、敗者復活、代表決定戦など多数の形式がある。

各format modelへMatchSimulatorを直接組み込むと、能力モデル接続コードが大会方式ごとに重複する。

## Decision

pre-MAINの勝敗もMAINと同じ `MatchResolution` を使う。

既存format modelは

- bracket shape
- pool assignment
- quota
- ranking
- stage transition

を管理し、1試合の勝敗だけをoptional match_resolverへ委譲する。

共通bracket層でscore / winner整合を検証し、full detailをCompetitionRunへ保存する。

## Consequences

### 利点

- 能力モデル接続点が共通化される
- 新format modelでも共通bracketを使えば自動的に能力試合対応できる
- MAIN/pre-MAINでresult保存形式が同じ
- resolver未指定時はlegacy behaviorを維持できる

### 注意

- 共通bracketを経由しない将来の特殊formatは別途MatchResolution対応が必要
- フルSeason ability実行は通常structural auditより重い
- season標準動作は当面resolver opt-inとする
