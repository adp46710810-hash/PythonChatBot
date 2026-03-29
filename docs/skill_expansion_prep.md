# スキル拡張準備メモ

このメモは「スキル追加前の準備」をまとめたものです。
まだ `data/balance/skills.json` へ本登録はしていません。

## 今回の準備で持てるようにした項目

- `max_level`
  - スキルごとに明示上限を持てる
  - `infinite_growth` と併用した場合も上限で停止する
- `levels[].special_effects`
  - まだ未実装の特殊効果を定義だけ置ける
  - 想定フィールドは `kind`, `summary`, `timing`, `target`, `params`, `tags`
- `infinite_growth.attack_multiplier_step`
  - 高倍率スキルの成長を手書き 20 レベルにせず調整できる
- `infinite_growth.action_gauge_bonus_step`
  - 行動ゲージ系の成長を持てる
- `infinite_growth.cooldown_actions_step`
  - 負数を許可
  - レベル上昇で CT を短くできる

## すぐ追加しやすい案

| 名前 | 仮ID | 種別 | Lv1 | Lv10 | Lv20 | 備考 |
| --- | --- | --- | --- | --- | --- | --- |
| 疾風 | `passive_hayate` | passive | S+8 | S+24 | S+40 | 周回・迅雷向け |
| 生命脈動 | `passive_life_pulse` | passive | HP+10 | HP+28 | HP+50 | 強行・WB向け |
| 紅蓮集中 | `active_crimson_focus` | active | A+8 2T / CT5 | A+18 2T / CT4 | A+28 3T / CT3 | 火力バフ |
| 城塞防陣 | `active_citadel_guard` | active | D+8 2T / CT5 | D+18 2T / CT4 | D+28 3T / CT3 | 防御バフ |
| 迅雷歩法 | `active_thunder_stride` | active | S+24 2T / CT5 | S+48 2T / CT4 | S+72 3T / CT3 | 速度バフ |
| 破城一閃 | `active_siege_break` | active | 攻x2.00 / CT6 | 攻x2.60 / CT5 | 攻x3.20 / CT4 | 高倍率単発 |
| 星導 | `active_star_guide` | active | 行動後ゲージ+25 x3T / CT6 | 行動後ゲージ+40 x3T / CT5 | 行動後ゲージ+55 x4T / CT4 | 特殊効果前提 |

## 特殊効果前提の案

| 名前 | 仮ID | kind | Lv1 | Lv10 | Lv20 | 備考 |
| --- | --- | --- | --- | --- | --- | --- |
| 吸命刃 | `active_blood_blade` | `lifesteal` | 攻x1.35 / 吸収12% / CT4 | 攻x1.50 / 吸収18% / CT4 | 攻x1.65 / 吸収24% / CT3 | 継戦型 |
| 崩し打ち | `active_guard_break` | `def_break` | 攻x1.15 / DEF-6 x2T / CT4 | 攻x1.20 / DEF-10 x2T / CT4 | 攻x1.30 / DEF-16 x3T / CT3 | ボス向け |
| 処刑人 | `active_executioner` | `execute` | 基礎x1.10 / 欠損補正上限+0.60 / CT4 | 基礎x1.25 / 欠損補正上限+0.90 / CT4 | 基礎x1.40 / 欠損補正上限+1.40 / CT3 | フィニッシャー |
| 追撃姿勢 | `passive_pursuit_stance` | `crit_followup` | 会心時追撃 1回/戦 | 会心時追撃 2回/戦 | 会心時追撃 3回/戦 | 会心ビルド向け |
| 収奪術 | `passive_plunder_master` | `drop_bonus` | ドロップ+5% | ドロップ+8% / 素材補正+1 | ドロップ+12% / 素材補正+1 | 周回軸 |
| 不屈 | `passive_indomitable` | `guts` | 致死耐え1回 / 残HP1 | 致死耐え1回 / 残HP8 | 致死耐え1回 / 残HP15 | 発動回数は固定 |

## 特殊効果の仮パラメータ案

- `lifesteal`
  - `heal_ratio`
- `def_break`
  - `def_down`
  - `duration_actions`
- `execute`
  - `base_multiplier`
  - `missing_hp_bonus_per_pct`
  - `bonus_cap`
- `crit_followup`
  - `max_triggers_per_battle`
  - `followup_multiplier`
- `drop_bonus`
  - `drop_rate_bonus`
  - `resource_roll_bonus`
- `guts`
  - `triggers`
  - `survive_hp`
- `action_gauge_regen`
  - `amount`
  - `duration_actions`

## 追加時の優先順

1. `疾風`
2. `生命脈動`
3. `紅蓮集中`
4. `城塞防陣`
5. `迅雷歩法`
6. `破城一閃`
7. `星導`
8. 特殊効果前提の 6 スキル

## 実装時メモ

- まずは「今のエンジンで動く 6 スキル」を先に入れる
- `星導` は `action_gauge_regen` の消化先を作ってから追加する
- `吸命刃` `崩し打ち` `処刑人` `追撃姿勢` `収奪術` `不屈` は `special_effects` を読む実行層ができてから本登録する
- 今後頻繁に数値調整する前提なので、強い単発技は `attack_multiplier_step` と `cooldown_actions_step` を使うと調整が楽
