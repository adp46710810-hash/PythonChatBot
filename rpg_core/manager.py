from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .battle_service import BattleService
from .exploration_service import ExplorationService
from .item_service import ItemService
from .rules import BEGINNER_GUARANTEE_AREA, POTION_PRICE, STARTER_POTION_COUNT
from .user_service import UserService
from .world_boss_service import WorldBossService


class RPGManager:
    def __init__(self, data: Dict[str, Any], *, owner_username: str = ""):
        self.data = data
        self.users = UserService(data, owner_username=owner_username)
        self.items = ItemService()
        self.battles = BattleService()
        self.exploration = ExplorationService(
            user_service=self.users,
            item_service=self.items,
            battle_service=self.battles,
        )
        self.world_boss = WorldBossService(
            data=self.data,
            user_service=self.users,
            battle_service=self.battles,
            owner_username=owner_username,
        )

    def _grant_starter_kit_if_needed(self, u: Dict[str, Any]) -> None:
        if bool(u.get("starter_kit_granted", False)):
            return

        equipped = u.setdefault("equipped", {})
        if not isinstance(equipped.get("weapon"), dict):
            starter_weapon = self.items.create_guaranteed_equipment(
                BEGINNER_GUARANTEE_AREA,
                "weapon",
                rarity="common",
            )
            if starter_weapon:
                self.users.assign_item_id(u, starter_weapon)
                equipped["weapon"] = starter_weapon

        u["potions"] = max(int(u.get("potions", 0)), int(STARTER_POTION_COUNT))
        u["starter_kit_granted"] = True

    def get_user(self, username: str) -> Dict[str, Any]:
        u = self.users.get_user(username)
        self._grant_starter_kit_if_needed(u)
        return u

    def get_adventure_level(self, u: Dict[str, Any]) -> int:
        return self.users.get_adventure_level(u)

    def get_level_exp(self, u: Dict[str, Any]) -> int:
        return self.users.get_level_exp(u)

    def get_max_hp_by_level(self, level: int) -> int:
        return self.users.get_max_hp_by_level(level)

    def get_equipped_item_power(self, u: Dict[str, Any], slot: str) -> int:
        return self.users.get_equipped_item_power(u, slot)

    def get_weapon_power(self, u: Dict[str, Any]) -> int:
        return self.users.get_weapon_power(u)

    def get_armor_power(self, u: Dict[str, Any]) -> int:
        return self.users.get_armor_power(u)

    def get_ring_power(self, u: Dict[str, Any]) -> int:
        return self.users.get_ring_power(u)

    def get_shoes_power(self, u: Dict[str, Any]) -> int:
        return self.users.get_shoes_power(u)

    def get_ring_mode_bonus(self, u: Dict[str, Any], mode_key: Optional[str]) -> Tuple[int, int]:
        return self.users.get_ring_mode_bonus(u, mode_key)

    def get_equipped_item_enchant_label(self, u: Dict[str, Any], slot: str) -> str:
        return self.users.get_equipped_item_enchant_label(u, slot)

    def is_slot_unlocked(self, u: Dict[str, Any], slot: str) -> bool:
        return self.users.is_slot_unlocked(u, slot)

    def get_unlocked_slots(self, u: Dict[str, Any]) -> Dict[str, bool]:
        return self.users.get_unlocked_slots(u)

    def is_feature_unlocked(self, u: Dict[str, Any], feature_key: str) -> bool:
        return self.users.is_feature_unlocked(u, feature_key)

    def is_auto_repeat_unlocked(self, u: Dict[str, Any]) -> bool:
        return self.users.is_auto_repeat_unlocked(u)

    def get_auto_repeat_progress(self, u: Dict[str, Any]) -> Dict[str, Any]:
        return self.users.get_auto_repeat_progress(u)

    def get_feature_effect_summaries(self, u: Dict[str, Any]) -> List[str]:
        return self.users.get_feature_effect_summaries(u)

    def get_unlocked_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_unlocked_passive_skills(u)

    def get_selected_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_selected_passive_skills(u)

    def get_unlocked_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_unlocked_active_skills(u)

    def get_locked_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_locked_passive_skills(u)

    def get_locked_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_locked_active_skills(u)

    def get_selected_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_selected_active_skills(u)

    def get_skill_level(self, u: Dict[str, Any], skill_id: str) -> int:
        return self.users.get_skill_level(u, skill_id)

    def get_skill_state(self, u: Dict[str, Any], skill_id: str) -> Optional[Dict[str, Any]]:
        return self.users.get_skill_state(u, skill_id)

    def get_passive_skill_bonuses(self, u: Dict[str, Any]) -> Dict[str, int]:
        return self.users.get_passive_skill_bonuses(u)

    def get_selected_active_skill(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.users.get_selected_active_skill(u)

    def format_selected_skill_slots(self, u: Dict[str, Any], skill_type: str) -> str:
        return self.users.format_selected_skill_slots(u, skill_type)

    def get_next_locked_skill(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.users.get_next_locked_skill(u)

    def set_selected_active_skill(self, username: str, skill_query: Optional[str]) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.set_selected_active_skill(u, skill_query)

    def set_selected_passive_skill(self, username: str, skill_query: Optional[str]) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.set_selected_passive_skill(u, skill_query)

    def set_selected_skill_loadout(
        self,
        username: str,
        skill_type: str,
        slot_queries: Dict[int, str],
    ) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.set_selected_skill_loadout(u, skill_type, slot_queries)

    def upgrade_skill(self, username: str, skill_query: Optional[str]) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.upgrade_skill(u, skill_query)

    def get_world_boss_material_inventory(self, u: Dict[str, Any]) -> Dict[str, int]:
        return self.users.get_world_boss_material_inventory(u)

    def get_world_boss_material_label(self, material_key: str) -> str:
        return self.users.get_world_boss_material_label(material_key)

    def get_world_boss_shop_catalog(self, u: Dict[str, Any]) -> Dict[str, Any]:
        return self.users.get_world_boss_shop_catalog(u)

    def exchange_world_boss_skill_books(
        self,
        username: str,
        item_query: Optional[str],
        quantity: Optional[int] = None,
    ) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.exchange_world_boss_skill_books(u, item_query, quantity=quantity)

    def get_weapon_crit_stats(self, u: Dict[str, Any]) -> Tuple[float, float]:
        return self.users.get_weapon_crit_stats(u)

    def get_weapon_crit_bonus_text(self, u: Dict[str, Any]) -> str:
        return self.users.get_weapon_crit_bonus_text(u)

    def get_ring_exploration_bonus_text(self, u: Dict[str, Any]) -> str:
        return self.users.get_ring_exploration_bonus_text(u)

    def get_armor_lethal_guard_count(self, u: Dict[str, Any]) -> int:
        return self.users.get_armor_lethal_guard_count(u)

    def get_player_atk(self, u: Dict[str, Any]) -> int:
        return self.users.get_player_atk(u)

    def get_player_def(self, u: Dict[str, Any]) -> int:
        return self.users.get_player_def(u)

    def get_player_speed(self, u: Dict[str, Any]) -> int:
        return self.users.get_player_speed(u)

    def get_player_combat_stats(self, u: Dict[str, Any], mode_key: Optional[str]) -> Tuple[int, int]:
        return self.users.get_player_combat_stats(u, mode_key)

    def get_player_stats(self, u: Dict[str, Any], mode_key: Optional[str]) -> Dict[str, int]:
        return self.users.get_player_stats(u, mode_key)

    def get_total_power(self, u: Dict[str, Any]) -> int:
        return self.users.get_total_power(u)

    def format_duration(self, sec: int) -> str:
        return self.users.format_duration(sec)

    def format_equipped_item(self, u: Dict[str, Any], slot: str) -> str:
        return self.users.format_equipped_item(u, slot)

    def format_item_brief(self, item: Dict[str, Any]) -> str:
        return self.users.format_item_brief(item)

    def get_sorted_bag_items(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_sorted_bag_items(u)

    def get_best_upgrade_candidates(self, u: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return self.users.get_best_upgrade_candidates(u)

    def get_material_inventory(self, u: Dict[str, Any]) -> Dict[str, int]:
        return self.users.get_material_inventory(u)

    def format_material_inventory(self, u: Dict[str, Any]) -> str:
        return self.users.format_material_inventory(u)

    def format_exploration_preparation_status(self, u: Dict[str, Any]) -> str:
        return self.users.format_exploration_preparation_status(u)

    def remember_display_name(self, username: str, display_name: Optional[str]) -> str:
        return self.users.remember_display_name(username, display_name)

    def get_display_name(self, username: str, fallback: Optional[str] = None) -> str:
        return self.users.get_display_name(username, fallback)

    def get_unlocked_achievements(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_unlocked_achievements(u)

    def get_unlocked_titles(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.users.get_unlocked_titles(u)

    def get_achievement_count(self, u: Dict[str, Any]) -> int:
        return self.users.get_achievement_count(u)

    def get_active_title(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.users.get_active_title(u)

    def get_active_title_label(self, u: Dict[str, Any]) -> str:
        return self.users.get_active_title_label(u)

    def set_active_title(self, username: str, title_query: Optional[str]) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.set_active_title(u, title_query)

    def format_titled_display_name(self, display_name: Optional[str], title_label: Optional[str]) -> str:
        return self.users.format_titled_display_name(display_name, title_label)

    def is_item_protected(self, u: Dict[str, Any], item_or_id: Any) -> bool:
        return self.users.is_item_protected(u, item_or_id)

    def set_item_protection(self, username: str, item_id: str, protected: bool) -> bool:
        u = self.users.get_user(username)
        return self.users.set_item_protection(u, item_id, protected)

    def get_exploration_history(self, u: Dict[str, Any], *, include_fallback: bool = True) -> List[Dict[str, Any]]:
        return self.users.get_exploration_history(u, include_fallback=include_fallback)

    def build_next_recommendation(self, u: Dict[str, Any]) -> Dict[str, Any]:
        return self.users.build_next_recommendation(u)

    def reward_chat_exp(self, u: Dict[str, Any], now: float) -> bool:
        return self.users.reward_chat_exp(u, now)

    def normalize_area_name(self, area: Optional[str]) -> str:
        return self.exploration.normalize_area_name(area)

    def resolve_exploration_mode(self, mode_key: Optional[str]) -> Dict[str, Any]:
        return self.exploration.resolve_exploration_mode(mode_key)

    def pick_monster(self, area_name: str) -> Dict[str, Any]:
        return self.exploration.pick_monster(area_name)

    def get_area_rarity_weights(self, area_name: str) -> List[Tuple[str, int]]:
        return self.items.get_area_rarity_weights(area_name)

    def roll_equipment_for_monster(
        self,
        area_name: str,
        monster_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self.items.roll_equipment_for_monster(area_name, monster_data)

    def calculate_exploration_duration(self, total_turns: int) -> int:
        return self.exploration.calculate_exploration_duration(total_turns)

    def get_safe_return_line(self, max_hp: int) -> int:
        return self.battles.get_safe_return_line(max_hp)

    def should_return_after_battle(self, current_hp: int, max_hp: int) -> bool:
        return self.battles.should_return_after_battle(current_hp, max_hp)

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
        active_skill: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.battles.should_start_battle(
            current_hp,
            player_atk,
            player_def,
            monster_data,
            max_hp,
            crit_chance=crit_chance,
            crit_damage_multiplier=crit_damage_multiplier,
            potion_heal=potion_heal,
            available_potions=available_potions,
            available_guards=available_guards,
            minimum_post_hp=minimum_post_hp,
            fatal_risk_last_hit_margin=fatal_risk_last_hit_margin,
            conservative_damage_check=conservative_damage_check,
            active_skill=active_skill,
        )

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
        active_skill: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.battles.simulate_battle(
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
            active_skill=active_skill,
        )

    def simulate_exploration_result(
        self,
        u: Dict[str, Any],
        area_name: str,
        mode: Optional[Dict[str, Any]] = None,
        preparation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved_mode = mode or self.exploration.resolve_exploration_mode(None)
        return self.exploration.simulate_exploration_result(
            u,
            area_name,
            resolved_mode,
            preparation=preparation,
        )

    def build_exploration_diagnosis(
        self,
        u: Dict[str, Any],
        request_text: Optional[str],
    ) -> Dict[str, Any]:
        return self.exploration.build_exploration_diagnosis(u, request_text)

    def buy_potions(self, username: str, qty: Optional[int] = None) -> Tuple[bool, str]:
        self.get_user(username)
        return self.users.buy_potions(username, qty, POTION_PRICE)

    def get_auto_potion_refill_target(self, u: Dict[str, Any]) -> int:
        return self.users.get_auto_potion_refill_target(u)

    def revive_user(self, username: str) -> Tuple[bool, str]:
        return self.users.revive_user(username)

    def debug_heal_user(self, username: str) -> Tuple[bool, str]:
        return self.users.debug_heal_user(username)

    def debug_add_gold(self, username: str, amount: int) -> Tuple[bool, str]:
        return self.users.debug_add_gold(username, amount)

    def debug_add_potions(self, username: str, amount: int) -> Tuple[bool, str]:
        return self.users.debug_add_potions(username, amount)

    def debug_add_adventure_exp(self, username: str, amount: int) -> Tuple[bool, str]:
        return self.users.debug_add_adventure_exp(username, amount)

    def debug_down_user(self, username: str) -> Tuple[bool, str]:
        return self.users.debug_down_user(username)

    def _get_pending_exploration_area(self, username: str) -> Optional[str]:
        user = self.get_user(username)
        explore = user.get("explore", {})
        if explore.get("state") != "exploring":
            return None
        result = explore.get("result")
        if isinstance(result, dict):
            area_name = str(result.get("area", "") or "").strip()
            if area_name:
                return area_name
        area_name = str(explore.get("area", "") or "").strip()
        return area_name or None

    def _get_pending_exploration_result(self, username: str) -> Optional[Dict[str, Any]]:
        user = self.get_user(username)
        explore = user.get("explore", {})
        if explore.get("state") != "exploring":
            return None
        result = explore.get("result")
        return result if isinstance(result, dict) else None

    def _get_pending_area_boss_clear_areas(self, username: str) -> List[str]:
        result = self._get_pending_exploration_result(username)
        if not isinstance(result, dict):
            return []
        return self.exploration.get_boss_clear_areas_from_result(result)

    def start_exploration(self, username: str, area_text: Optional[str]) -> Tuple[bool, str]:
        self.get_user(username)
        return self.exploration.start_exploration(username, area_text)

    def prepare_exploration(self, username: str, slot: str) -> Tuple[bool, str]:
        u = self.get_user(username)
        return self.users.prepare_exploration(u, slot)

    def finalize_exploration(self, username: str) -> str:
        boss_clear_areas = self._get_pending_area_boss_clear_areas(username)
        message = self.exploration.finalize_exploration(username)
        for area_name in boss_clear_areas:
            self.world_boss.record_area_boss_clear(area_name)
        return message

    def try_finalize_exploration(self, username: str) -> Optional[str]:
        boss_clear_areas = self._get_pending_area_boss_clear_areas(username)
        message = self.exploration.try_finalize_exploration(username)
        if message:
            for area_name in boss_clear_areas:
                self.world_boss.record_area_boss_clear(area_name)
        return message

    def has_legendary_drop(self, result: Optional[Dict[str, Any]]) -> bool:
        return self.exploration.has_legendary_drop(result)

    def stop_auto_repeat(self, username: str) -> Tuple[bool, str]:
        return self.exploration.stop_auto_repeat(username)

    def list_world_bosses(self) -> List[Dict[str, Any]]:
        return self.world_boss.list_boss_templates()

    def get_world_boss_status(self, username: Optional[str] = None) -> Dict[str, Any]:
        return self.world_boss.get_status(username)

    def get_world_boss_summon_material_cost(self) -> int:
        return self.world_boss.get_summon_material_cost()

    def start_world_boss(self, boss_id: Optional[str] = None) -> Tuple[bool, str]:
        return self.world_boss.start_boss(boss_id)

    def summon_world_boss(self, username: str) -> Tuple[bool, Dict[str, Any]]:
        return self.world_boss.summon_boss(username)

    def join_world_boss(self, username: str) -> Tuple[bool, str]:
        return self.world_boss.join_boss(username)

    def leave_world_boss(self, username: str) -> Tuple[bool, str]:
        return self.world_boss.leave_boss(username)

    def skip_world_boss(self) -> Tuple[bool, str]:
        return self.world_boss.skip_recruiting()

    def stop_world_boss(self) -> Tuple[bool, str]:
        return self.world_boss.stop_boss()

    def process_world_boss(self) -> Tuple[List[str], bool]:
        return self.world_boss.process()

    def get_last_world_boss_result(self, username: str) -> Optional[Dict[str, Any]]:
        return self.world_boss.get_user_last_result(username)

    def autoequip_best(self, username: str) -> bool:
        u = self.users.get_user(username)
        changed = self.items.autoequip_best(u)
        if changed:
            self.users.sync_level_stats(u)
        return changed

    def enhance_equipped_item(self, username: str, slot: str) -> Tuple[bool, str]:
        u = self.users.get_user(username)
        attempted, message = self.items.enhance_equipped_item(u, slot)
        if attempted:
            self.users.sync_level_stats(u)
        return attempted, message

    def auto_enhance_equipped_items(
        self,
        username: str,
        slots: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        u = self.users.get_user(username)
        summary = self.items.auto_enhance_equipped_items(u, slots=slots)
        if bool(summary.get("attempted", False)):
            self.users.sync_level_stats(u)
        return summary

    def enchant_equipped_item(self, username: str, slot: str) -> Tuple[bool, str]:
        u = self.users.get_user(username)
        return self.items.enchant_equipped_item(u, slot)

    def sell_all_bag_items(self, username: str) -> Tuple[int, int]:
        u = self.users.get_user(username)
        return self.items.sell_all_bag_items(u)
