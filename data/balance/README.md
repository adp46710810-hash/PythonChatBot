# RPG Balance Data

`data/balance` 配下の JSON を編集すると、モンスターや装備まわりの調整がしやすくなります。

## Files

- `areas.json`: エリアごとの `tier`、金額補正、レア補正、別名 (`aliases`) を定義
- `areas.json`: エリアごとの `material_drop` / `material_drops` / `enchantment_drops`、`specialty`、`max_rarity`、`level_exp_scaling`、`battle_scaling` を定義できます
- `monsters.json`: エリアごとの出現モンスターと基礎ステータスを定義
- `skills.json`: 初期所持スキル、スロット、強化段階、WB素材コスト、戦闘中のステータス上昇量を定義
- `world_bosses.json`: リアルタイムWBのHP、攻撃力、募集時間、報酬、専用素材を定義
- `equipment.json`: 装備レアリティ、接頭辞、スロット名、生成パワー計算と強化・エンチャント設定を定義

## Main tuning points

- モンスターの強さ: `monsters.json` の `hp` / `atk` / `def` / `exp` / `gold`
- 出現率: `monsters.json` の `weight`
- 装備ドロップ率の地形差: `areas.json` の `drop_rate_bonus`
- エリア経験値補正: `areas.json` の `exp_rate` と `level_exp_scaling`
- 戦闘後半の伸び方: `areas.json` の `battle_scaling`
- 戦闘後半の追加報酬: `areas.json` の `battle_scaling` にある `late_exp_*` / `late_gold_*` / `late_drop_rate_*` / `late_resource_*`
- スキルの強化段階と必要WB素材: `skills.json`
- レア装備の出やすさ: `areas.json` の `rare_bonus` と `equipment.json` の `base_rarity_weights`
- 装備レア上限: `areas.json` の `max_rarity`
- 装備の伸び幅: `equipment.json` の `power_per_tier` / `power_roll_min` / `power_roll_max`
- 装備の出現スロット比率: `equipment.json` の `slot_drop_weights`
- 強化素材名: `equipment.json` の `material_labels`
- エンチャント素材名と効果、武器クリティカル率や強化値連動の伸び: `equipment.json` の `enchantment`
- 素材探索地の単独/複合ドロップ: `areas.json` の `material_drop` / `material_drops`
- エンチャント素材ドロップ: `areas.json` の `enchantment_drops`
- 強化率と必要コスト、強化上限: `equipment.json` の `enhancement`
- リアルタイムWBの募集時間、制限時間、報酬: `world_bosses.json`

## Notes

- JSON を壊すと起動時にエラーになります。
- `equipment.enhancement.success_rates` は、`max_level` と同じ数だけ用意すると各強化段階の成功率を個別に調整できます。
- `equipment.enhancement.endgame_start_level` を境に、`material_cost_endgame_step` と `gold_cost_endgame_step` で終盤強化コストを上乗せできます。`10` にすると `+10 -> +11` から追加コストが発生します。
- `equipment.enhancement.deep_endgame_start_level` を追加すると、さらに後半だけ別の上乗せを入れられます。`15` にすると `+15 -> +16` から追加コストが発生します。
- 数値を変えたら、ボットを再起動すると反映されます。
- 探索モード、致死耐性、武器のクリティカル、装飾のモード別A/D補正、探索時間計算などのコード側ルールは `rpg_core/rules.py` を調整します。
