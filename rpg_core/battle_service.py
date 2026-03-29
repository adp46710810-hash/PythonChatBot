from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .rules import DEFAULT_MONSTER_SPEED, SAFE_RETURN_HP_RATIO, SAFE_RETURN_MIN_HP
from .stat_helpers import GAUGE_THRESHOLD, merge_stats, nonzero_stats, normalize_stats


class BattleService:
    def _normalize_special_effects(self, raw_effects: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_effects, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for raw_effect in raw_effects:
            if not isinstance(raw_effect, dict):
                continue
            raw_params = raw_effect.get("params", {})
            if not isinstance(raw_params, dict):
                raw_params = {}
            normalized.append(
                {
                    "kind": str(raw_effect.get("kind", "") or "").strip(),
                    "summary": str(raw_effect.get("summary", "") or "").strip(),
                    "timing": str(raw_effect.get("timing", "") or "").strip(),
                    "target": str(raw_effect.get("target", "") or "").strip(),
                    "params": dict(raw_params),
                    "tags": [
                        str(tag).strip()
                        for tag in raw_effect.get("tags", [])
                        if str(tag).strip()
                    ]
                    if isinstance(raw_effect.get("tags", []), list)
                    else [],
                }
            )
        return normalized

    def get_base_damage(
        self,
        attacker_atk: int,
        defender_def: int,
    ) -> int:
        return max(1, int(attacker_atk) - int(defender_def))

    def roll_attack_damage(
        self,
        attacker_atk: int,
        defender_def: int,
        *,
        crit_chance: float = 0.0,
        crit_damage_multiplier: float = 1.0,
    ) -> tuple[int, bool]:
        base_damage = self.get_base_damage(attacker_atk, defender_def)
        clamped_crit_chance = min(1.0, max(0.0, float(crit_chance)))
        clamped_crit_multiplier = max(1.0, float(crit_damage_multiplier))
        if random.random() < clamped_crit_chance:
            return max(1, int(round(base_damage * clamped_crit_multiplier))), True
        return base_damage, False

    def _get_expected_player_damage(
        self,
        attacker_atk: int,
        defender_def: int,
        crit_chance: float,
        crit_damage_multiplier: float,
    ) -> int:
        base_damage = self.get_base_damage(attacker_atk, defender_def)
        clamped_crit_chance = min(1.0, max(0.0, float(crit_chance)))
        clamped_crit_multiplier = max(1.0, float(crit_damage_multiplier))
        expected_multiplier = 1.0 + (clamped_crit_chance * (clamped_crit_multiplier - 1.0))
        return max(1, int(round(base_damage * expected_multiplier)))

    def normalize_auto_skill(self, raw_skill: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw_skill, dict):
            return {}
        special_effects = self._normalize_special_effects(raw_skill.get("special_effects", []))
        stats = normalize_stats(
            raw_skill.get(
                "stats",
                {
                    "atk": raw_skill.get("atk_bonus", 0),
                    "def": raw_skill.get("def_bonus", 0),
                    "speed": raw_skill.get("speed_bonus", 0),
                    "max_hp": raw_skill.get("max_hp_bonus", 0),
                },
            )
        )
        duration_actions = max(
            0,
            int(
                raw_skill.get(
                    "duration_actions",
                    raw_skill.get(
                        "duration_turns",
                        raw_skill.get("duration_ticks", 0),
                    ),
                )
                or 0
            ),
        )
        return {
            "skill_id": str(raw_skill.get("skill_id", "") or "").strip(),
            "name": str(raw_skill.get("name", "") or "").strip() or "スキル",
            "target": str(raw_skill.get("target", "single_enemy") or "single_enemy").strip(),
            "deals_damage": bool(raw_skill.get("deals_damage", True)),
            "stats": nonzero_stats(stats),
            "duration_actions": duration_actions,
            "cooldown_actions": max(0, int(raw_skill.get("cooldown_actions", 0) or 0)),
            "attack_multiplier": max(0.0, float(raw_skill.get("attack_multiplier", 1.0) or 1.0)),
            "action_gauge_bonus": max(0, int(raw_skill.get("action_gauge_bonus", 0) or 0)),
            "special_effects": special_effects,
        }

    def normalize_auto_skills(
        self,
        raw_skills: Optional[List[Dict[str, Any]]] = None,
        *,
        legacy_skill: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        candidates = list(raw_skills or [])
        if legacy_skill and not candidates:
            candidates.append(legacy_skill)
        for raw_skill in candidates[:4]:
            skill = self.normalize_auto_skill(raw_skill)
            if not skill:
                continue
            normalized.append(skill)
        return normalized

    def build_unit_state(
        self,
        *,
        unit_id: str,
        name: str,
        base_stats: Dict[str, Any],
        current_hp: int,
        crit_chance: float = 0.0,
        crit_damage_multiplier: float = 1.0,
        active_skills: Optional[List[Dict[str, Any]]] = None,
        order: int = 0,
    ) -> Dict[str, Any]:
        safe_stats = normalize_stats(base_stats)
        max_hp = max(1, int(safe_stats.get("max_hp", 1)))
        return {
            "unit_id": str(unit_id or "").strip() or name,
            "name": str(name or "").strip() or "ユニット",
            "base_stats": safe_stats,
            "current_hp": max(0, min(int(current_hp), max_hp)),
            "action_gauge": 0,
            "crit_chance": min(1.0, max(0.0, float(crit_chance))),
            "crit_damage_multiplier": max(1.0, float(crit_damage_multiplier)),
            "active_skills": self.normalize_auto_skills(active_skills),
            "skill_cooldowns": {},
            "active_effects": [],
            "order": int(order),
            "alive": int(current_hp) > 0,
        }

    def get_unit_stats(self, unit: Dict[str, Any]) -> Dict[str, int]:
        effect_stats = [effect.get("stats", {}) for effect in unit.get("active_effects", []) if isinstance(effect, dict)]
        return merge_stats(unit.get("base_stats", {}), *effect_stats)

    def advance_action_gauges(self, units: List[Dict[str, Any]]) -> None:
        for unit in units:
            if not isinstance(unit, dict):
                continue
            if int(unit.get("current_hp", 0)) <= 0 or not bool(unit.get("alive", True)):
                continue
            speed = max(1, int(self.get_unit_stats(unit).get("speed", 1) or 1))
            unit["action_gauge"] = (
                max(0, int(unit.get("action_gauge", 0)))
                + speed
                + self.get_unit_action_gauge_regen_bonus(unit)
            )

    def get_ready_units(self, units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ready_units = [
            unit
            for unit in units
            if isinstance(unit, dict)
            and bool(unit.get("alive", True))
            and int(unit.get("current_hp", 0)) > 0
            and int(unit.get("action_gauge", 0)) >= GAUGE_THRESHOLD
        ]
        return sorted(
            ready_units,
            key=lambda unit: (
                -int(unit.get("action_gauge", 0)),
                -int(self.get_unit_stats(unit).get("speed", 0)),
                int(unit.get("order", 0)),
            ),
        )

    def select_auto_skill(self, unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cooldowns = unit.setdefault("skill_cooldowns", {})
        for skill in unit.get("active_skills", [])[:4]:
            if not isinstance(skill, dict):
                continue
            skill_id = str(skill.get("skill_id", "") or "").strip()
            if skill_id and int(cooldowns.get(skill_id, 0) or 0) > 0:
                continue
            return dict(skill)
        return None

    def consume_action_gauge(self, unit: Dict[str, Any]) -> None:
        unit["action_gauge"] = max(0, int(unit.get("action_gauge", 0)) - GAUGE_THRESHOLD)

    def _tick_unit_effects(self, unit: Dict[str, Any]) -> None:
        remaining_effects: List[Dict[str, Any]] = []
        for effect in unit.get("active_effects", []):
            if not isinstance(effect, dict):
                continue
            actions_left = max(0, int(effect.get("actions_left", 0) or 0) - 1)
            if actions_left <= 0:
                continue
            remaining_effect = dict(effect)
            remaining_effect["actions_left"] = actions_left
            remaining_effects.append(remaining_effect)
        unit["active_effects"] = remaining_effects

    def _tick_unit_cooldowns(self, unit: Dict[str, Any]) -> None:
        cooldowns = unit.setdefault("skill_cooldowns", {})
        for skill_id in list(cooldowns):
            remaining = max(0, int(cooldowns.get(skill_id, 0) or 0) - 1)
            if remaining <= 0:
                cooldowns.pop(skill_id, None)
                continue
            cooldowns[skill_id] = remaining

    def finalize_unit_action(
        self,
        unit: Dict[str, Any],
        *,
        used_skill: Optional[Dict[str, Any]] = None,
        new_effect: Optional[Dict[str, Any]] = None,
        action_gauge_bonus: int = 0,
    ) -> None:
        self.consume_action_gauge(unit)
        self._tick_unit_effects(unit)
        self._tick_unit_cooldowns(unit)
        if new_effect:
            unit.setdefault("active_effects", []).append(dict(new_effect))
        if used_skill:
            skill_id = str(used_skill.get("skill_id", "") or "").strip()
            if skill_id:
                cooldown = max(0, int(used_skill.get("cooldown_actions", 0) or 0))
                if cooldown > 0:
                    unit.setdefault("skill_cooldowns", {})[skill_id] = cooldown
        if action_gauge_bonus > 0 and int(unit.get("current_hp", 0)) > 0 and bool(unit.get("alive", True)):
            unit["action_gauge"] = max(0, int(unit.get("action_gauge", 0))) + max(0, int(action_gauge_bonus))

    def create_skill_effect(self, skill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        duration_actions = max(0, int(skill.get("duration_actions", 0) or 0))
        if duration_actions <= 0:
            return None
        stats = nonzero_stats(skill.get("stats", {}))
        special_effects = self._normalize_special_effects(skill.get("special_effects", []))
        if special_effects:
            resolved_special_effects: List[Dict[str, Any]] = []
            for special_effect in special_effects:
                resolved_special_effect = dict(special_effect)
                params = dict(resolved_special_effect.get("params", {}))
                if (
                    str(resolved_special_effect.get("kind", "") or "").strip() == "action_gauge_regen"
                    and "amount" not in params
                ):
                    params["amount"] = self.get_skill_action_gauge_bonus(skill)
                resolved_special_effect["params"] = params
                resolved_special_effects.append(resolved_special_effect)
            special_effects = resolved_special_effects
        if not stats and not special_effects:
            return None
        return {
            "skill_id": str(skill.get("skill_id", "") or "").strip(),
            "name": str(skill.get("name", "") or "").strip() or "スキル",
            "stats": stats,
            "actions_left": duration_actions,
            "special_effects": special_effects,
        }

    def get_unit_action_gauge_regen_bonus(self, unit: Dict[str, Any]) -> int:
        total_bonus = 0
        for effect in unit.get("active_effects", []):
            if not isinstance(effect, dict):
                continue
            for special_effect in self._normalize_special_effects(effect.get("special_effects", [])):
                if str(special_effect.get("kind", "") or "").strip() != "action_gauge_regen":
                    continue
                params = special_effect.get("params", {})
                if not isinstance(params, dict):
                    continue
                total_bonus += max(0, int(params.get("amount", 0) or 0))
        return total_bonus

    def get_skill_attack_multiplier(self, skill: Optional[Dict[str, Any]]) -> float:
        if not isinstance(skill, dict):
            return 1.0
        return max(0.0, float(skill.get("attack_multiplier", 1.0) or 1.0))

    def get_skill_action_gauge_bonus(self, skill: Optional[Dict[str, Any]]) -> int:
        if not isinstance(skill, dict):
            return 0
        return max(0, int(skill.get("action_gauge_bonus", 0) or 0))

    def get_skill_defense_ignore_rate(self, skill: Optional[Dict[str, Any]]) -> float:
        if not isinstance(skill, dict):
            return 0.0
        ignore_rate = 0.0
        for effect in self._normalize_special_effects(skill.get("special_effects", [])):
            kind = str(effect.get("kind", "") or "").strip()
            if kind not in {"defense_ignore", "ignore_defense"}:
                continue
            params = effect.get("params", {})
            if not isinstance(params, dict):
                continue
            raw_rate = params.get("rate", params.get("ratio", 0.0))
            try:
                ignore_rate = max(ignore_rate, float(raw_rate))
            except (TypeError, ValueError):
                continue
        return min(1.0, max(0.0, float(ignore_rate)))

    def get_effective_defense(self, defender_def: int, skill: Optional[Dict[str, Any]] = None) -> int:
        base_def = max(0, int(defender_def))
        ignore_rate = self.get_skill_defense_ignore_rate(skill)
        if ignore_rate <= 0.0:
            return base_def
        return max(0, int(round(base_def * (1.0 - ignore_rate))))

    def skill_has_special_effect(self, skill: Optional[Dict[str, Any]], kind: str) -> bool:
        if not isinstance(skill, dict):
            return False
        safe_kind = str(kind or "").strip()
        if not safe_kind:
            return False
        return any(
            str(effect.get("kind", "") or "").strip() == safe_kind
            for effect in self._normalize_special_effects(skill.get("special_effects", []))
        )

    def skill_deals_damage(self, skill: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(skill, dict):
            return False
        return bool(skill.get("deals_damage", True))

    def scale_damage_for_skill(self, damage: int, skill: Optional[Dict[str, Any]]) -> int:
        base_damage = max(1, int(damage))
        multiplier = self.get_skill_attack_multiplier(skill)
        if abs(multiplier - 1.0) < 1e-9:
            return base_damage
        return max(1, int(round(base_damage * multiplier)))

    def _apply_enemy_attack(
        self,
        player_hp: int,
        damage: int,
        lethal_guards_left: int,
    ) -> tuple[int, int, bool]:
        next_hp = player_hp - damage
        if next_hp <= 0 and lethal_guards_left > 0:
            return 1, lethal_guards_left - 1, True
        return max(0, next_hp), lethal_guards_left, False

    def _format_skill_activation(self, skill: Dict[str, Any]) -> str:
        parts = []
        stats = normalize_stats(skill.get("stats", {}))
        if int(stats.get("atk", 0)) > 0:
            parts.append(f"A+{int(stats['atk'])}")
        if int(stats.get("def", 0)) > 0:
            parts.append(f"D+{int(stats['def'])}")
        if int(stats.get("speed", 0)) > 0:
            parts.append(f"S+{int(stats['speed'])}")
        if int(stats.get("max_hp", 0)) > 0:
            parts.append(f"HP+{int(stats['max_hp'])}")
        attack_multiplier = self.get_skill_attack_multiplier(skill)
        if abs(attack_multiplier - 1.0) >= 1e-9:
            parts.append(f"攻x{attack_multiplier:.2f}")
        action_gauge_bonus = self.get_skill_action_gauge_bonus(skill)
        if action_gauge_bonus > 0 and not self.skill_has_special_effect(skill, "action_gauge_regen"):
            parts.append(f"行動+{action_gauge_bonus}")
        for special_effect in self._normalize_special_effects(skill.get("special_effects", [])):
            summary = str(special_effect.get("summary", "") or "").strip()
            if summary:
                parts.append(summary)
        text = f"スキル発動 {str(skill.get('name', 'スキル') or 'スキル').strip()}"
        if parts:
            text += " " + " / ".join(parts)
        return text

    def _run_battle(
        self,
        player_hp: int,
        player_atk: int,
        player_def: int,
        monster_data: Dict[str, Any],
        *,
        max_hp: int,
        crit_chance: float,
        crit_damage_multiplier: float,
        potion_heal: int,
        available_potions: int,
        available_guards: int,
        capture_log: bool,
        deterministic_crit: bool,
        conservative_damage_check: bool = False,
        active_skill: Dict[str, Any] | None = None,
        active_skills: Optional[List[Dict[str, Any]]] = None,
        player_speed: int = 100,
        enemy_speed: Optional[int] = None,
    ) -> Dict[str, Any]:
        enemy_hp = int(monster_data.get("hp", 1))
        effective_enemy_speed = max(1, int(monster_data.get("speed", enemy_speed or DEFAULT_MONSTER_SPEED) or DEFAULT_MONSTER_SPEED))
        player_unit = self.build_unit_state(
            unit_id="player",
            name="自分",
            base_stats={"atk": player_atk, "def": player_def, "speed": player_speed, "max_hp": max_hp},
            current_hp=player_hp,
            crit_chance=crit_chance,
            crit_damage_multiplier=crit_damage_multiplier,
            active_skills=self.normalize_auto_skills(active_skills, legacy_skill=active_skill),
            order=0,
        )
        enemy_unit = self.build_unit_state(
            unit_id="enemy",
            name=str(monster_data.get("name", "敵") or "敵"),
            base_stats={
                "atk": int(monster_data.get("atk", 1)),
                "def": int(monster_data.get("def", 0)),
                "speed": effective_enemy_speed,
                "max_hp": enemy_hp,
            },
            current_hp=enemy_hp,
            order=1,
        )

        start_player_hp = player_hp
        turn_count = 0
        action_count = 0
        potions_left = max(0, int(available_potions))
        potions_used = 0
        lethal_guards_left = max(0, int(available_guards))
        effective_max_hp = max(int(max_hp), int(player_hp), 1)
        battle_log: List[str] = []
        turn_details: List[Dict[str, Any]] = []
        escaped = False
        dmg_to_enemy = 1
        dmg_to_player = 1
        enemy_attack_count = 0

        while int(player_unit.get("current_hp", 0)) > 0 and int(enemy_unit.get("current_hp", 0)) > 0:
            turn_count += 1
            turn_player_hp_start = int(player_unit.get("current_hp", 0))
            turn_enemy_hp_start = int(enemy_unit.get("current_hp", 0))
            player_actions: List[str] = []
            enemy_actions: List[str] = []
            guarded = False

            self.advance_action_gauges([player_unit, enemy_unit])
            ready_units = self.get_ready_units([player_unit, enemy_unit])
            if not ready_units:
                if capture_log:
                    battle_log.append(f"T{turn_count}: 行動なし")
                turn_details.append(
                    {
                        "turn": turn_count,
                        "player_hp_start": turn_player_hp_start,
                        "enemy_hp_start": turn_enemy_hp_start,
                        "player_hp_end": max(0, int(player_unit.get("current_hp", 0))),
                        "enemy_hp_end": max(0, int(enemy_unit.get("current_hp", 0))),
                        "player_action": "行動なし",
                        "enemy_action": "行動なし",
                        "guarded": False,
                    }
                )
                continue

            while ready_units:
                actor = ready_units[0]
                defender = enemy_unit if actor is player_unit else player_unit
                actor_stats = self.get_unit_stats(actor)
                defender_stats = self.get_unit_stats(defender)
                action_count += 1

                if actor is player_unit:
                    selected_skill = self.select_auto_skill(player_unit)
                    skill_effect = self.create_skill_effect(selected_skill) if selected_skill else None
                    skill_activation_text = self._format_skill_activation(selected_skill) if selected_skill else ""
                    skill_deals_damage = self.skill_deals_damage(selected_skill)
                    skill_action_gauge_bonus = self.get_skill_action_gauge_bonus(selected_skill)
                    if skill_effect and self.skill_has_special_effect(selected_skill, "action_gauge_regen"):
                        skill_action_gauge_bonus = 0
                    action_stats = merge_stats(
                        actor_stats,
                        selected_skill.get("stats", {}) if selected_skill and not skill_effect else {},
                    )
                    effective_enemy_def = self.get_effective_defense(
                        int(defender_stats.get("def", 0)),
                        selected_skill,
                    )

                    dmg_to_enemy = (
                        self.get_base_damage(int(action_stats.get("atk", 1)), effective_enemy_def)
                        if conservative_damage_check
                        else self._get_expected_player_damage(
                            int(action_stats.get("atk", 1)),
                            effective_enemy_def,
                            crit_chance=float(player_unit.get("crit_chance", 0.0)),
                            crit_damage_multiplier=float(player_unit.get("crit_damage_multiplier", 1.0)),
                        )
                    )
                    if selected_skill and not skill_effect and skill_deals_damage:
                        dmg_to_enemy = self.scale_damage_for_skill(dmg_to_enemy, selected_skill)
                    dmg_to_player = self.get_base_damage(
                        int(enemy_unit.get("base_stats", {}).get("atk", 1)),
                        int(action_stats.get("def", 0)),
                    )

                    can_use_potion = (
                        potions_left > 0
                        and potion_heal > 0
                        and int(player_unit.get("current_hp", 0)) < effective_max_hp
                    )
                    healed_hp = (
                        min(effective_max_hp, int(player_unit.get("current_hp", 0)) + potion_heal)
                        if can_use_potion
                        else int(player_unit.get("current_hp", 0))
                    )
                    should_use_potion = (
                        int(enemy_unit.get("current_hp", 0)) > dmg_to_enemy
                        and can_use_potion
                        and int(player_unit.get("current_hp", 0)) <= dmg_to_player
                        and healed_hp > dmg_to_player
                    )

                    if should_use_potion:
                        before_hp = int(player_unit.get("current_hp", 0))
                        player_unit["current_hp"] = healed_hp
                        potions_left -= 1
                        potions_used += 1
                        player_action_text = f"ポーション使用 {before_hp}→{healed_hp}"
                        player_actions.append(player_action_text)
                        if capture_log:
                            battle_log.append(f"T{turn_count}: 自分 {player_action_text}")
                        self.finalize_unit_action(player_unit)
                    elif selected_skill and skill_effect:
                        player_action_text = skill_activation_text
                        player_actions.append(player_action_text)
                        if capture_log:
                            battle_log.append(f"T{turn_count}: 自分 {player_action_text}")
                        self.finalize_unit_action(
                            player_unit,
                            used_skill=selected_skill,
                            new_effect=skill_effect,
                            action_gauge_bonus=skill_action_gauge_bonus,
                        )
                    elif selected_skill and not skill_deals_damage:
                        player_action_text = skill_activation_text or "スキル発動"
                        player_actions.append(player_action_text)
                        if capture_log:
                            battle_log.append(f"T{turn_count}: 自分 {player_action_text}")
                        self.finalize_unit_action(
                            player_unit,
                            used_skill=selected_skill,
                            action_gauge_bonus=skill_action_gauge_bonus,
                        )
                    else:
                        if deterministic_crit:
                            dealt_to_enemy = self._get_expected_player_damage(
                                int(action_stats.get("atk", 1)),
                                effective_enemy_def,
                                crit_chance=float(player_unit.get("crit_chance", 0.0)),
                                crit_damage_multiplier=float(player_unit.get("crit_damage_multiplier", 1.0)),
                            )
                            critical_hit = dealt_to_enemy > self.get_base_damage(
                                int(action_stats.get("atk", 1)),
                                effective_enemy_def,
                            )
                        else:
                            dealt_to_enemy, critical_hit = self.roll_attack_damage(
                                int(action_stats.get("atk", 1)),
                                effective_enemy_def,
                                crit_chance=float(player_unit.get("crit_chance", 0.0)),
                                crit_damage_multiplier=float(player_unit.get("crit_damage_multiplier", 1.0)),
                            )
                        if selected_skill and not skill_effect:
                            dealt_to_enemy = self.scale_damage_for_skill(dealt_to_enemy, selected_skill)
                        defender["current_hp"] = max(0, int(defender.get("current_hp", 0)) - dealt_to_enemy)
                        crit_prefix = "会心! " if critical_hit else ""
                        player_action_text = f"自分→{monster_data['name']} {crit_prefix}{dealt_to_enemy}ダメ"
                        if skill_activation_text:
                            player_action_text = f"{skill_activation_text} / {player_action_text}"
                        player_actions.append(player_action_text)
                        if capture_log:
                            battle_log.append(f"T{turn_count}: {player_action_text}")
                        self.finalize_unit_action(
                            player_unit,
                            used_skill=selected_skill,
                            action_gauge_bonus=skill_action_gauge_bonus,
                        )
                else:
                    dmg_to_player = self.get_base_damage(
                        int(actor_stats.get("atk", 1)),
                        int(defender_stats.get("def", 0)),
                    )
                    enemy_attack_count += 1
                    next_hp, lethal_guards_left, action_guarded = self._apply_enemy_attack(
                        int(player_unit.get("current_hp", 0)),
                        dmg_to_player,
                        lethal_guards_left,
                    )
                    player_unit["current_hp"] = next_hp
                    enemy_action_text = f"{monster_data['name']}→自分 {dmg_to_player}ダメ"
                    enemy_actions.append(enemy_action_text)
                    guarded = guarded or bool(action_guarded)
                    if capture_log:
                        battle_log.append(f"T{turn_count}: {enemy_action_text}")
                        if action_guarded:
                            battle_log.append(f"T{turn_count}: 防具が致命傷を防ぎ HP1 で踏みとどまった")
                    self.finalize_unit_action(enemy_unit)
                    if action_guarded:
                        escaped = True

                if escaped or int(player_unit.get("current_hp", 0)) <= 0 or int(enemy_unit.get("current_hp", 0)) <= 0:
                    break
                ready_units = self.get_ready_units([player_unit, enemy_unit])

            turn_details.append(
                {
                    "turn": turn_count,
                    "player_hp_start": turn_player_hp_start,
                    "enemy_hp_start": turn_enemy_hp_start,
                    "player_hp_end": max(0, int(player_unit.get("current_hp", 0))),
                    "enemy_hp_end": max(0, int(enemy_unit.get("current_hp", 0))),
                    "player_action": " / ".join(player_actions) if player_actions else "行動なし",
                    "enemy_action": " / ".join(enemy_actions) if enemy_actions else "行動なし",
                    "guarded": bool(guarded),
                }
            )

            if escaped or int(player_unit.get("current_hp", 0)) <= 0 or int(enemy_unit.get("current_hp", 0)) <= 0:
                break

        return {
            "won": int(enemy_unit.get("current_hp", 0)) <= 0 and int(player_unit.get("current_hp", 0)) > 0 and not escaped,
            "escaped": escaped,
            "player_hp_after": max(0, int(player_unit.get("current_hp", 0))),
            "enemy_hp_after": max(0, int(enemy_unit.get("current_hp", 0))),
            "damage_taken": max(0, start_player_hp - max(0, int(player_unit.get("current_hp", 0)))),
            "turns": turn_count,
            "log": battle_log[:8] if capture_log else [],
            "turn_details": turn_details if capture_log else [],
            "potions_used": potions_used,
            "guards_used": max(0, int(available_guards) - lethal_guards_left),
            "guards_left": lethal_guards_left,
            "dmg_to_enemy": max(1, int(dmg_to_enemy)),
            "dmg_to_player": max(1, int(dmg_to_player)),
            "enemy_attack_count": enemy_attack_count,
            "action_count": action_count,
        }

    def estimate_battle(
        self,
        current_hp: int,
        player_atk: int,
        player_def: int,
        monster_data: Dict[str, Any],
        max_hp: int,
        crit_chance: float = 0.0,
        crit_damage_multiplier: float = 1.0,
        potion_heal: int = 0,
        available_potions: int = 0,
        available_guards: int = 0,
        conservative_damage_check: bool = False,
        active_skill: Dict[str, Any] | None = None,
        active_skills: Optional[List[Dict[str, Any]]] = None,
        player_speed: int = 100,
        enemy_speed: Optional[int] = None,
    ) -> Dict[str, Any]:
        simulated = self._run_battle(
            current_hp,
            player_atk,
            player_def,
            monster_data,
            max_hp=max_hp,
            crit_chance=crit_chance,
            crit_damage_multiplier=crit_damage_multiplier,
            potion_heal=potion_heal,
            available_potions=available_potions,
            available_guards=available_guards,
            capture_log=False,
            deterministic_crit=True,
            conservative_damage_check=conservative_damage_check,
            active_skill=active_skill,
            active_skills=active_skills,
            player_speed=player_speed,
            enemy_speed=enemy_speed,
        )
        simulated["turns_to_kill_enemy"] = max(1, int(simulated.get("turns", 0) or 0))
        simulated["enemy_attack_count"] = max(0, int(simulated.get("enemy_attack_count", 0) or 0))
        simulated["predicted_damage"] = int(simulated.get("damage_taken", 0))
        simulated["can_win"] = bool(simulated.get("won", False))
        return simulated

    def get_safe_return_line(
        self,
        max_hp: int,
        safe_return_ratio: float = SAFE_RETURN_HP_RATIO,
        safe_return_min_hp: int = SAFE_RETURN_MIN_HP,
    ) -> int:
        return max(int(safe_return_min_hp), int(max_hp * float(safe_return_ratio)))

    def should_return_after_battle(
        self,
        current_hp: int,
        max_hp: int,
        safe_return_ratio: float = SAFE_RETURN_HP_RATIO,
        safe_return_min_hp: int = SAFE_RETURN_MIN_HP,
    ) -> bool:
        return current_hp <= self.get_safe_return_line(
            max_hp,
            safe_return_ratio=safe_return_ratio,
            safe_return_min_hp=safe_return_min_hp,
        )

    def should_start_battle(
        self,
        current_hp: int,
        player_atk: int,
        player_def: int,
        monster_data: Dict[str, Any],
        max_hp: int,
        crit_chance: float = 0.0,
        crit_damage_multiplier: float = 1.0,
        potion_heal: int = 0,
        available_potions: int = 0,
        available_guards: int = 0,
        minimum_post_hp: int = 1,
        fatal_risk_last_hit_margin: int = 0,
        conservative_damage_check: bool = False,
        active_skill: Dict[str, Any] | None = None,
        active_skills: Optional[List[Dict[str, Any]]] = None,
        player_speed: int = 100,
        enemy_speed: Optional[int] = None,
    ) -> bool:
        estimate = self.estimate_battle(
            current_hp,
            player_atk,
            player_def,
            monster_data,
            max_hp=max_hp,
            crit_chance=crit_chance,
            crit_damage_multiplier=crit_damage_multiplier,
            potion_heal=potion_heal,
            available_potions=available_potions,
            available_guards=available_guards,
            conservative_damage_check=conservative_damage_check,
            active_skill=active_skill,
            active_skills=active_skills,
            player_speed=player_speed,
            enemy_speed=enemy_speed,
        )
        required_post_hp = max(1, int(minimum_post_hp))
        if bool(estimate["can_win"]) and int(estimate["player_hp_after"]) >= required_post_hp:
            return True

        guard_can_save_battle = (
            int(available_guards) > 0
            and bool(estimate.get("escaped", False))
            and int(estimate.get("guards_used", 0)) > 0
        )
        if guard_can_save_battle:
            return True

        close_fatal_risk_battle = (
            int(fatal_risk_last_hit_margin) > 0
            and not bool(estimate.get("can_win", False))
            and int(estimate.get("enemy_hp_after", 0)) > 0
            and int(estimate.get("enemy_hp_after", 0))
            <= max(1, int(estimate.get("dmg_to_enemy", 1))) * max(1, int(fatal_risk_last_hit_margin))
        )
        if close_fatal_risk_battle:
            return True

        return False

    def simulate_battle(
        self,
        player_hp: int,
        player_atk: int,
        player_def: int,
        monster_data: Dict[str, Any],
        max_hp: int,
        crit_chance: float = 0.0,
        crit_damage_multiplier: float = 1.0,
        potion_heal: int = 0,
        available_potions: int = 0,
        available_guards: int = 0,
        active_skill: Dict[str, Any] | None = None,
        active_skills: Optional[List[Dict[str, Any]]] = None,
        player_speed: int = 100,
        enemy_speed: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._run_battle(
            player_hp,
            player_atk,
            player_def,
            monster_data,
            max_hp=max_hp,
            crit_chance=crit_chance,
            crit_damage_multiplier=crit_damage_multiplier,
            potion_heal=potion_heal,
            available_potions=available_potions,
            available_guards=available_guards,
            capture_log=True,
            deterministic_crit=False,
            active_skill=active_skill,
            active_skills=active_skills,
            player_speed=player_speed,
            enemy_speed=enemy_speed,
        )
