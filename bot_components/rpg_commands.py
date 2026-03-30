from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from twitchio.ext import commands

from app_config import CONFIG
from rpg_core.exploration_result import (
    format_return_footer,
    get_actual_battle_logs,
    get_battle_count,
)
from rpg_core.rules import (
    AUTO_EXPLORE_STONE_NAME,
    ENCHANTMENT_MATERIAL_LABELS,
    AREA_ALIASES,
    AREAS,
    BEGINNER_GUARANTEE_AREA,
    BEGINNER_GUARANTEE_MAX_LEVEL,
    DEFAULT_AREA,
    DEFAULT_EXPLORATION_MODE,
    DEFAULT_MAX_HP,
    EXPLORATION_MODE_CONFIG,
    FEATURE_UNLOCK_LABELS,
    MATERIAL_LABELS,
    MAX_POTIONS_PER_EXPLORATION,
    POTION_PRICE,
    SLOT_LABEL,
)
from rpg_core.utils import nfkc, now_ts


class BasicCommands(commands.Component):
    def __init__(self, bot: "StreamBot") -> None:
        self.bot = bot

    def _is_owner(self, ctx: commands.Context) -> bool:
        return str(getattr(ctx.chatter, "id", "")) == str(self.bot.owner_id)

    def _get_identity(self, ctx: commands.Context) -> Tuple[str, str]:
        username = (
            getattr(ctx.chatter, "name", None)
            or getattr(ctx.chatter, "login", None)
            or ""
        ).lower()
        display_name = (
            getattr(ctx.chatter, "display_name", None)
            or getattr(ctx.chatter, "name", None)
            or username
        )
        return username, self.bot.rpg.remember_display_name(username, display_name)

    def _get_target_identity(
        self,
        ctx: commands.Context,
        target_name: Optional[str],
    ) -> Tuple[str, str]:
        if target_name:
            target = target_name.lower()
            display_name = self.bot.rpg.get_display_name(target, target_name)
            return target, display_name

        target, display_name = self._get_identity(ctx)
        return target, display_name

    def _normalize_slot(self, slot_text: Optional[str]) -> Optional[str]:
        text = (slot_text or "").strip().lower()
        aliases = {
            "weapon": "weapon",
            "武器": "weapon",
            "ぶき": "weapon",
            "armor": "armor",
            "防具": "armor",
            "ぼうぐ": "armor",
            "ring": "ring",
            "装飾": "ring",
            "装飾品": "ring",
            "アクセ": "ring",
            "アクセサリ": "ring",
            "アクセサリー": "ring",
            "shoes": "shoes",
            "shoe": "shoes",
            "靴": "shoes",
            "くつ": "shoes",
        }
        return aliases.get(text)

    def _split_subcommand(self, text: Optional[str]) -> Tuple[str, str]:
        normalized = nfkc(str(text or "")).strip()
        if not normalized:
            return "", ""
        parts = normalized.split(maxsplit=1)
        head = parts[0].lower()
        tail = parts[1].strip() if len(parts) > 1 else ""
        return head, tail

    async def _dispatch_subcommand(
        self,
        ctx: commands.Context,
        subcommand: str,
        remainder: str,
        routes: List[Tuple[set[str], Any, Optional[str]]],
    ) -> bool:
        if not subcommand:
            return False

        for aliases, callback, arg_name in routes:
            if subcommand not in aliases:
                continue
            kwargs = {}
            if arg_name:
                kwargs[arg_name] = remainder or None
            await callback(self, ctx, **kwargs)
            return True
        return False

    def _show_help_topic(
        self,
        display_name: str,
        command_name: str,
        detail_lines: List[str],
        reply_label: str,
    ) -> str:
        self._show_detail_overlay(
            f"{display_name} / {command_name}",
            detail_lines,
        )
        return self._build_detail_hint_reply(display_name, reply_label)

    def _get_discord_invite_url(self) -> str:
        getter = getattr(self.bot, "get_discord_invite_url", None)
        if callable(getter):
            try:
                invite_url = str(getter() or "").strip()
                if invite_url:
                    return invite_url
            except Exception:
                pass
        return str(getattr(CONFIG, "discord_invite_url", "") or "").strip()

    def _looks_like_exploration_shortcut(self, text: Optional[str]) -> bool:
        normalized = nfkc(str(text or "")).strip().lower()
        if not normalized:
            return False

        recognized_tokens = {
            nfkc(area_name).strip().lower()
            for area_name in AREAS
            if nfkc(area_name).strip()
        }
        recognized_tokens.update(
            nfkc(alias).strip().lower()
            for alias in AREA_ALIASES
            if nfkc(alias).strip()
        )
        recognized_tokens.update({"自動", "自動周回", "周回", "auto", "loop", "repeat"})
        for mode_key, config in EXPLORATION_MODE_CONFIG.items():
            safe_mode_key = nfkc(str(mode_key or "")).strip().lower()
            if safe_mode_key:
                recognized_tokens.add(safe_mode_key)
            for alias in config.get("aliases", ()):
                safe_alias = nfkc(str(alias or "")).strip().lower()
                if safe_alias:
                    recognized_tokens.add(safe_alias)

        if normalized in recognized_tokens:
            return True

        head = normalized.split(maxsplit=1)[0]
        return head in recognized_tokens

    def _parse_int_argument(self, text: Optional[str]) -> Tuple[Optional[int], str]:
        head, tail = self._split_subcommand(text)
        if not head:
            return None, ""
        try:
            return int(head), tail
        except ValueError:
            return None, str(text or "").strip()

    def _looks_like_indexed_skill_loadout(self, text: Optional[str]) -> bool:
        normalized = nfkc(str(text or "")).strip()
        if not normalized:
            return False
        return normalized.split(maxsplit=1)[0].isdigit()

    def _parse_indexed_skill_loadout(self, text: Optional[str]) -> Tuple[Dict[int, str], Optional[str]]:
        normalized = nfkc(str(text or "")).strip()
        if not normalized:
            return {}, "スロット番号とスキル名を指定してください。"

        tokens = normalized.split()
        assignments: Dict[int, str] = {}
        index = 0
        while index < len(tokens):
            if not tokens[index].isdigit():
                return {}, "スロット番号は `1 スキル名 2 スキル名` の形で指定してください。"
            slot_index = int(tokens[index])
            if slot_index in assignments:
                return {}, f"スロット{slot_index} が重複しています。"
            index += 1
            if index >= len(tokens) or tokens[index].isdigit():
                return {}, f"スロット{slot_index} のスキル名を指定してください。"

            skill_tokens: List[str] = []
            while index < len(tokens) and not tokens[index].isdigit():
                skill_tokens.append(tokens[index])
                index += 1
            assignments[slot_index] = " ".join(skill_tokens).strip()

        if not assignments:
            return {}, "スロット番号とスキル名を指定してください。"
        return assignments, None

    def _parse_trailing_int_argument(self, text: Optional[str]) -> Tuple[str, Optional[int]]:
        normalized = nfkc(str(text or "")).strip()
        if not normalized:
            return "", None
        parts = normalized.rsplit(maxsplit=1)
        if len(parts) == 1:
            return normalized, None
        try:
            return parts[0].strip(), int(parts[1])
        except ValueError:
            return normalized, None

    def _get_world_boss_selector_entries(self) -> List[Tuple[int, str, str]]:
        entries: List[Tuple[int, str, str]] = []
        for index, boss in enumerate(self.bot.rpg.list_world_bosses(), start=1):
            if not isinstance(boss, dict):
                continue
            boss_id = str(boss.get("boss_id", "") or "").strip()
            if not boss_id:
                continue
            boss_name = str(boss.get("name", "") or "").strip() or boss_id
            entries.append((index, boss_id, boss_name))
        return entries

    def _format_world_boss_selector_options(
        self,
        entries: Optional[List[Tuple[int, str, str]]] = None,
    ) -> str:
        safe_entries = entries if entries is not None else self._get_world_boss_selector_entries()
        formatted = []
        for index, boss_id, boss_name in safe_entries:
            formatted.append(f"{index}:{boss_name} ({boss_id})")
        return " / ".join(formatted)

    def _resolve_world_boss_selector(self, selector: Optional[str]) -> Tuple[Optional[str], str]:
        safe_selector = nfkc(str(selector or "")).strip()
        if not safe_selector:
            return None, ""

        entries = self._get_world_boss_selector_entries()
        if not entries:
            return None, ""

        selector_key = safe_selector.lower()
        for index, boss_id, boss_name in entries:
            if selector_key == boss_id.lower():
                return boss_id, ""
            if selector_key == nfkc(boss_name).strip().lower():
                return boss_id, ""
            if safe_selector.isdigit() and int(safe_selector) == index:
                return boss_id, ""
        return None, self._format_world_boss_selector_options(entries)

    def _get_slot_order(self) -> List[str]:
        preferred = ("weapon", "armor", "ring", "shoes")
        ordered = [slot_name for slot_name in preferred if slot_name in SLOT_LABEL]
        ordered.extend(slot_name for slot_name in SLOT_LABEL if slot_name not in ordered)
        return ordered

    def _format_ring_bonus(self, user) -> str:
        if not self.bot.rpg.is_slot_unlocked(user, "ring"):
            return "未開放"

        ring_power = self.bot.rpg.get_ring_power(user)
        ring_enchant = self.bot.rpg.get_equipped_item_enchant_label(user, "ring")
        if ring_power <= 0 and not ring_enchant:
            return "補正なし"

        parts = []
        if ring_power > 0:
            cautious_atk, cautious_def = self.bot.rpg.get_ring_mode_bonus(user, "cautious")
            reckless_atk, reckless_def = self.bot.rpg.get_ring_mode_bonus(user, "reckless")
            parts.append(
                f"慎重A{cautious_atk:+d}/D{cautious_def:+d} "
                f"強行A{reckless_atk:+d}/D{reckless_def:+d}"
            )
        if ring_enchant:
            parts.append(ring_enchant)
            exploration_bonus = self.bot.rpg.get_ring_exploration_bonus_text(user)
            if exploration_bonus:
                parts.append(exploration_bonus)
        return " / ".join(parts) if parts else "補正なし"

    def _format_weapon_bonus(self, user) -> str:
        weapon_enchant = self.bot.rpg.get_equipped_item_enchant_label(user, "weapon")
        if not weapon_enchant:
            return "補正なし"

        weapon_bonus = self.bot.rpg.get_weapon_crit_bonus_text(user)
        if weapon_bonus:
            return f"{weapon_enchant} / {weapon_bonus}"
        return weapon_enchant

    def _format_slot_enchant_status(self, user, slot: str) -> str:
        if not self.bot.rpg.is_slot_unlocked(user, slot):
            return "未開放"
        return self.bot.rpg.get_equipped_item_enchant_label(user, slot) or "なし"

    def _format_guard_status_for_user(self, user) -> str:
        if not self.bot.rpg.is_slot_unlocked(user, "armor"):
            return "未開放"
        return self._format_guard_status(self.bot.rpg.get_armor_lethal_guard_count(user))

    def _format_guard_count_for_user(self, user) -> str:
        if not self.bot.rpg.is_slot_unlocked(user, "armor"):
            return "未開放"
        return f"{self.bot.rpg.get_armor_lethal_guard_count(user)}回"

    def _format_equipment_summary(self, user) -> str:
        return " / ".join(
            f"{SLOT_LABEL.get(slot_name, slot_name)} {self.bot.rpg.format_equipped_item(user, slot_name)}"
            for slot_name in self._get_slot_order()
        )

    def _format_skill_effect_summary(self, skill: Optional[Dict[str, Any]]) -> str:
        if not isinstance(skill, dict):
            return "なし"

        parts: List[str] = []
        atk_bonus = max(0, int(skill.get("atk_bonus", skill.get("atk", 0)) or 0))
        def_bonus = max(0, int(skill.get("def_bonus", skill.get("def", 0)) or 0))
        speed_bonus = max(0, int(skill.get("speed_bonus", skill.get("speed", 0)) or 0))
        max_hp_bonus = max(0, int(skill.get("max_hp_bonus", skill.get("max_hp", 0)) or 0))
        if atk_bonus > 0:
            parts.append(f"A+{atk_bonus}")
        if def_bonus > 0:
            parts.append(f"D+{def_bonus}")
        if speed_bonus > 0:
            parts.append(f"S+{speed_bonus}")
        if max_hp_bonus > 0:
            parts.append(f"HP+{max_hp_bonus}")

        attack_multiplier = max(0.0, float(skill.get("attack_multiplier", 1.0) or 1.0))
        if abs(attack_multiplier - 1.0) >= 1e-9:
            parts.append(f"攻x{attack_multiplier:.2f}")

        has_action_gauge_regen = any(
            isinstance(effect, dict) and str(effect.get("kind", "") or "").strip() == "action_gauge_regen"
            for effect in skill.get("special_effects", [])
            if isinstance(skill.get("special_effects", []), list)
        )
        action_gauge_bonus = max(0, int(skill.get("action_gauge_bonus", 0) or 0))
        if action_gauge_bonus > 0 and not has_action_gauge_regen:
            parts.append(f"行動+{action_gauge_bonus}")

        if str(skill.get("type", "") or "").strip() == "active":
            duration_turns = max(0, int(skill.get("duration_turns", 0) or 0))
            if duration_turns > 0:
                parts.append(f"{duration_turns}T")
            cooldown_actions = max(0, int(skill.get("cooldown_actions", 0) or 0))
            if cooldown_actions > 0:
                parts.append(f"CT{cooldown_actions}")

        special_effect_summaries = skill.get("special_effect_summaries", [])
        if not isinstance(special_effect_summaries, list):
            special_effect_summaries = []
        for summary in special_effect_summaries[:2]:
            safe_summary = str(summary or "").strip()
            if safe_summary:
                parts.append(safe_summary)

        return " / ".join(parts) if parts else "補正なし"

    def _format_skill_label(self, skill: Optional[Dict[str, Any]]) -> str:
        if not isinstance(skill, dict):
            return "なし"
        return (
            f"{str(skill.get('name', '') or '').strip() or 'スキル'} "
            f"Lv{max(1, int(skill.get('skill_level', 1) or 1))}"
        )

    def _format_skill_loadout_summary(self, user: Dict[str, Any]) -> str:
        selected_active = self.bot.rpg.get_selected_active_skill(user)
        if isinstance(selected_active, dict):
            return f"A:{self._format_skill_label(selected_active)}"

        passive_skills = getattr(self.bot.rpg, "get_selected_passive_skills", lambda _user: [])(user)
        passive_labels = [
            self._format_skill_label(skill)
            for skill in passive_skills[:3]
            if isinstance(skill, dict)
        ]
        if passive_labels:
            return f"P:{' / '.join(passive_labels)}"
        return "なし"

    def _format_skill_slot_summary(self, user: Dict[str, Any], skill_type: str) -> str:
        formatter = getattr(self.bot.rpg, "format_selected_skill_slots", None)
        if callable(formatter):
            return str(formatter(user, skill_type) or "なし")

        getter_name = "get_selected_passive_skills" if skill_type == "passive" else "get_selected_active_skills"
        getter = getattr(self.bot.rpg, getter_name, None)
        if not callable(getter):
            return "なし"
        skills = getter(user)
        if not isinstance(skills, list):
            return "なし"
        labels = [
            f"{index}:{self._format_skill_label(skill)}"
            for index, skill in enumerate(skills, start=1)
            if isinstance(skill, dict)
        ]
        return " / ".join(labels) if labels else "なし"

    def _format_titled_display_name(self, display_name: str, title_label: Optional[str]) -> str:
        formatter = getattr(self.bot.rpg, "format_titled_display_name", None)
        if callable(formatter):
            return formatter(display_name, title_label)
        safe_display_name = str(display_name or "?").strip() or "?"
        safe_title_label = str(title_label or "").strip()
        if not safe_title_label:
            return safe_display_name
        return f"[{safe_title_label}] {safe_display_name}"

    def _get_active_title_label(self, user: Dict[str, Any]) -> str:
        getter = getattr(self.bot.rpg, "get_active_title_label", None)
        if not callable(getter):
            return ""
        return str(getter(user) or "").strip()

    def _get_achievement_count(self, user: Dict[str, Any]) -> int:
        getter = getattr(self.bot.rpg, "get_achievement_count", None)
        if not callable(getter):
            return 0
        return max(0, int(getter(user)))

    def _get_unlocked_titles(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        getter = getattr(self.bot.rpg, "get_unlocked_titles", None)
        if not callable(getter):
            return []
        titles = getter(user)
        if not isinstance(titles, list):
            return []
        return [title for title in titles if isinstance(title, dict)]

    def _get_unlocked_achievements(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        getter = getattr(self.bot.rpg, "get_unlocked_achievements", None)
        if not callable(getter):
            return []
        achievements = getter(user)
        if not isinstance(achievements, list):
            return []
        return [achievement for achievement in achievements if isinstance(achievement, dict)]

    def _build_title_detail_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        unlocked_titles = self._get_unlocked_titles(user)
        unlocked_achievements = self._get_unlocked_achievements(user)
        active_title_label = self._get_active_title_label(user)

        lines = [
            "コマンド: !称号",
            f"ユーザー: {display_name}",
            f"現在称号: {active_title_label or 'なし'}",
            f"称号数: {len(unlocked_titles)} / 実績数: {self._get_achievement_count(user)}",
        ]
        if unlocked_titles:
            lines.append("所持称号:")
            for title in unlocked_titles[:10]:
                title_label = str(title.get("title_label", "") or title.get("title", "")).strip() or "称号"
                marker = " [装備中]" if title_label == active_title_label and active_title_label else ""
                lines.append(
                    f"- {title_label}{marker} / 実績 {str(title.get('name', '実績') or '実績').strip()}"
                )
        else:
            lines.append("所持称号: まだありません")

        if unlocked_achievements:
            lines.append(
                "主な実績: "
                + " / ".join(
                    str(achievement.get("name", "実績") or "実績").strip()
                    for achievement in unlocked_achievements[:6]
                )
            )
        lines.append("切替: !称号 変更 <名前> / !称号 変更 解除")
        return [line for line in lines if line]

    def _build_title_reply(self, display_name: str, user: Dict[str, Any]) -> str:
        active_title_label = self._get_active_title_label(user)
        unlocked_titles = self._get_unlocked_titles(user)
        return self._build_detail_hint_reply(
            display_name,
            "称号",
            f"現在 {active_title_label or 'なし'}",
            f"所持 {len(unlocked_titles)}件",
        )

    def _format_skill_upgrade_cost_summary(self, user: Dict[str, Any], skill: Optional[Dict[str, Any]]) -> str:
        if not isinstance(skill, dict):
            return "なし"
        if bool(skill.get("is_max_level", False)):
            return "MAX"

        costs = skill.get("next_upgrade_costs", {})
        if not isinstance(costs, dict) or not costs:
            return "不要"

        inventory = self.bot.rpg.get_world_boss_material_inventory(user)
        parts: List[str] = []
        for material_key, required_amount in sorted(costs.items()):
            safe_required_amount = max(0, int(required_amount))
            current_amount = self._get_available_world_boss_material_amount(inventory, material_key)
            parts.append(
                f"{self.bot.rpg.get_world_boss_material_label(material_key)} {current_amount}/{safe_required_amount}"
            )
        return " / ".join(parts) if parts else "不要"

    def _is_skill_book_material_key(self, material_key: Any) -> bool:
        safe_material_key = str(material_key or "").strip()
        return safe_material_key == "skill_book" or safe_material_key.startswith("skill_book:")

    def _get_available_world_boss_material_amount(
        self,
        inventory: Dict[str, Any],
        material_key: Any,
    ) -> int:
        safe_material_key = str(material_key or "").strip()
        amount = max(0, int(inventory.get(safe_material_key, 0) or 0))
        if safe_material_key.startswith("skill_book:"):
            amount += max(0, int(inventory.get("skill_book", 0) or 0))
        return amount

    def _format_world_boss_materials_summary(self, user: Dict[str, Any]) -> str:
        inventory = self.bot.rpg.get_world_boss_material_inventory(user)
        parts = [
            f"{self.bot.rpg.get_world_boss_material_label(material_key)}x{int(amount)}"
            for material_key, amount in sorted(
                inventory.items(),
                key=lambda entry: (
                    not self._is_skill_book_material_key(entry[0]),
                    self.bot.rpg.get_world_boss_material_label(entry[0]),
                ),
            )
            if int(amount) > 0
        ]
        return " / ".join(parts) if parts else "なし"

    def _format_world_boss_base_materials_summary(self, user: Dict[str, Any]) -> str:
        inventory = self.bot.rpg.get_world_boss_material_inventory(user)
        parts = [
            f"{self.bot.rpg.get_world_boss_material_label(material_key)}x{int(amount)}"
            for material_key, amount in sorted(
                inventory.items(),
                key=lambda entry: self.bot.rpg.get_world_boss_material_label(entry[0]),
            )
            if int(amount) > 0 and not self._is_skill_book_material_key(material_key)
        ]
        return " / ".join(parts) if parts else "なし"

    def _format_skill_book_holdings_summary(self, shop: Dict[str, Any]) -> str:
        parts: List[str] = []
        legacy_label = str(shop.get("legacy_skill_book_label", "スキルの書") or "スキルの書").strip() or "スキルの書"
        legacy_amount = max(0, int(shop.get("legacy_skill_book_amount", 0) or 0))
        if legacy_amount > 0:
            parts.append(f"{legacy_label}x{legacy_amount}")

        for target in shop.get("skill_book_targets", []):
            if not isinstance(target, dict):
                continue
            amount = max(0, int(target.get("current_amount", 0) or 0))
            if amount <= 0:
                continue
            label = str(target.get("skill_book_label", "スキルの書") or "スキルの書").strip() or "スキルの書"
            parts.append(f"{label}x{amount}")

        return " / ".join(parts) if parts else "なし"

    def _build_locked_skill_preview(self, skill: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(skill, dict):
            return None
        levels = skill.get("levels", [])
        if not isinstance(levels, list) or not levels:
            return None
        first_level = dict(levels[0]) if isinstance(levels[0], dict) else {}
        preview = dict(skill)
        preview.update(
            {
                "skill_level": 1,
                "stats": dict(first_level.get("stats", {})),
                "atk_bonus": max(0, int(first_level.get("atk_bonus", 0) or 0)),
                "def_bonus": max(0, int(first_level.get("def_bonus", 0) or 0)),
                "speed_bonus": max(0, int(first_level.get("speed_bonus", 0) or 0)),
                "max_hp_bonus": max(0, int(first_level.get("max_hp_bonus", 0) or 0)),
                "duration_turns": max(0, int(first_level.get("duration_turns", 0) or 0)),
                "duration_ticks": max(0, int(first_level.get("duration_ticks", 0) or 0)),
                "cooldown_actions": max(0, int(first_level.get("cooldown_actions", 0) or 0)),
                "attack_multiplier": max(0.0, float(first_level.get("attack_multiplier", 1.0) or 1.0)),
                "action_gauge_bonus": max(0, int(first_level.get("action_gauge_bonus", 0) or 0)),
                "level_description": str(first_level.get("description", skill.get("description", "")) or "").strip(),
            }
        )
        return preview

    def _format_locked_skill_unlock_cost_summary(self, user: Dict[str, Any], skill: Optional[Dict[str, Any]]) -> str:
        if not isinstance(skill, dict):
            return "なし"
        levels = skill.get("levels", [])
        if not isinstance(levels, list) or not levels or not isinstance(levels[0], dict):
            return "なし"
        costs = dict(levels[0].get("upgrade_costs", {}))
        if not costs:
            return "不要"
        inventory = self.bot.rpg.get_world_boss_material_inventory(user)
        skill_book_key = f"skill_book:{str(skill.get('skill_id', '') or '').strip()}"
        parts: List[str] = []
        for material_key, required_amount in sorted(costs.items()):
            display_key = material_key
            if str(material_key or "").strip() == "skill_book" and str(skill.get("skill_id", "") or "").strip():
                display_key = skill_book_key
            safe_required_amount = max(0, int(required_amount))
            current_amount = self._get_available_world_boss_material_amount(inventory, display_key)
            parts.append(
                f"{self.bot.rpg.get_world_boss_material_label(display_key)} {current_amount}/{safe_required_amount}"
            )
        return " / ".join(parts) if parts else "不要"

    def _build_skill_detail_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        passive_skills = self.bot.rpg.get_unlocked_passive_skills(user)
        active_skills = self.bot.rpg.get_unlocked_active_skills(user)
        locked_passive_skills = getattr(self.bot.rpg, "get_locked_passive_skills", lambda _user: [])(user)
        locked_active_skills = getattr(self.bot.rpg, "get_locked_active_skills", lambda _user: [])(user)
        equipped_passives = getattr(self.bot.rpg, "get_selected_passive_skills", lambda _user: [])(user)
        equipped_actives = getattr(self.bot.rpg, "get_selected_active_skills", lambda _user: [])(user)
        selected_active = self.bot.rpg.get_selected_active_skill(user)

        lines = [
            "コマンド: !スキル",
            f"ユーザー: {display_name}",
            (
                f"優先アクティブ: {self._format_skill_label(selected_active)} / "
                f"{self._format_skill_effect_summary(selected_active)}"
                if isinstance(selected_active, dict)
                else "優先アクティブ: なし"
            ),
            f"WB所持品: {self._format_world_boss_materials_summary(user)}",
            "交換: !wb ショップ / !wb 交換 <スキル名> [冊数]",
        ]

        if passive_skills:
            lines.append("パッシブ:")
            equipped_passive_ids = {
                str(skill.get("skill_id", "") or "").strip()
                for skill in equipped_passives
                if isinstance(skill, dict)
            }
            for skill in passive_skills:
                equipped_marker = " [装備中]" if str(skill.get("skill_id", "") or "").strip() in equipped_passive_ids else ""
                detail = str(skill.get("level_description", "") or "").strip() or self._format_skill_effect_summary(skill)
                lines.append(f"- {self._format_skill_label(skill)}{equipped_marker} / {detail}")
                lines.append(f"次強化: {self._format_skill_upgrade_cost_summary(user, skill)}")

        if active_skills:
            lines.append("アクティブ:")
            equipped_active_ids = [
                str(skill.get("skill_id", "") or "").strip()
                for skill in equipped_actives
                if isinstance(skill, dict)
            ]
            for skill in active_skills:
                safe_skill_id = str(skill.get("skill_id", "") or "").strip()
                marker = ""
                if safe_skill_id in equipped_active_ids:
                    marker = f" [優先{equipped_active_ids.index(safe_skill_id) + 1}]"
                detail = str(skill.get("level_description", "") or "").strip() or self._format_skill_effect_summary(skill)
                lines.append(f"- {self._format_skill_label(skill)}{marker} / {detail}")
                lines.append(f"次強化: {self._format_skill_upgrade_cost_summary(user, skill)}")
        else:
            lines.append("アクティブ: なし")

        if locked_passive_skills:
            lines.append("未所持パッシブ:")
            for skill in locked_passive_skills:
                preview = self._build_locked_skill_preview(skill) or skill
                detail = str(preview.get("level_description", "") or "").strip() or self._format_skill_effect_summary(preview)
                lines.append(f"- {self._format_skill_label(preview)} [未所持] / {detail}")
                lines.append(f"解放: {self._format_locked_skill_unlock_cost_summary(user, skill)}")

        if locked_active_skills:
            lines.append("未所持アクティブ:")
            for skill in locked_active_skills:
                preview = self._build_locked_skill_preview(skill) or skill
                detail = str(preview.get("level_description", "") or "").strip() or self._format_skill_effect_summary(preview)
                lines.append(f"- {self._format_skill_label(preview)} [未所持] / {detail}")
                lines.append(f"解放: {self._format_locked_skill_unlock_cost_summary(user, skill)}")

        lines.append("切替: !スキル 変更 <スキル名> / !スキル変更 パッシブ 1 闘魂 2 鉄壁 3 迅雷")
        lines.append("強化: !スキル強化 <スキル名> (所持ぶん自動)")
        return lines

    def _build_skill_reply(self, display_name: str, user: Dict[str, Any]) -> str:
        selected_active = self.bot.rpg.get_selected_active_skill(user)
        if isinstance(selected_active, dict):
            return self._build_detail_hint_reply(
                display_name,
                self._format_skill_label(selected_active),
                self._format_skill_effect_summary(selected_active),
                f"次強化 {self._format_skill_upgrade_cost_summary(user, selected_active)}",
            )
        selected_passives = getattr(self.bot.rpg, "get_selected_passive_skills", lambda _user: [])(user)
        if selected_passives:
            primary_passive = dict(selected_passives[0])
            return self._build_detail_hint_reply(
                display_name,
                self._format_skill_label(primary_passive),
                self._format_skill_effect_summary(primary_passive),
                f"装備中P{len(selected_passives)}",
            )
        return self._build_detail_hint_reply(
            display_name,
            "スキルなし",
        )

    def _show_detail_overlay(self, title: str, lines: List[str]) -> None:
        publisher = getattr(self.bot, "publish_detail_response", None)
        if callable(publisher):
            publisher(title, lines)
            return
        self.bot.show_detail_overlay(title, lines)

    def _refresh_world_boss_overlay_live(
        self,
        display_name: str,
        username: Optional[str] = None,
    ) -> None:
        status = self.bot.rpg.get_world_boss_status(username)
        self.bot.show_detail_overlay(
            f"{display_name} / !wb",
            self._build_world_boss_status_lines(display_name, status),
        )

    def _detail_destination_label(self) -> str:
        getter = getattr(self.bot, "get_detail_destination_label", None)
        if callable(getter):
            label = str(getter() or "").strip()
            if label:
                return label
        return "OBS"

    def _build_detail_hint_reply(self, *segments: object, limit: int = 220) -> str:
        parts = [str(segment).strip() for segment in segments if str(segment).strip()]
        parts.append(f"詳細は{self._detail_destination_label()}")
        return self._truncate_chat_text(" / ".join(parts), limit=limit)

    def _overlay_section(self, title: str) -> str:
        safe_title = str(title or "").strip()
        return f"section: {safe_title}" if safe_title else ""

    def _overlay_kv(self, label: str, value: Any, *, alert: bool = False) -> str:
        safe_label = str(label or "").strip()
        safe_value = str(value or "").strip()
        prefix = "alert: " if alert else ""
        if safe_label and safe_value:
            return f"{prefix}kv: {safe_label} | {safe_value}"
        if safe_value:
            return f"{prefix}{safe_value}"
        return f"{prefix}{safe_label}".strip()

    def _append_chunked_values(
        self,
        lines: List[str],
        label: str,
        values: List[str],
        *,
        chunk_size: int = 3,
    ) -> None:
        if not values:
            lines.append(f"{label}: なし")
            return

        for index in range(0, len(values), max(1, int(chunk_size))):
            chunk = values[index : index + max(1, int(chunk_size))]
            current_label = label if index == 0 else f"{label}+"
            lines.append(f"{current_label}: {' / '.join(chunk)}")

    def _build_material_line(
        self,
        drop_materials: Dict[str, Any],
        drop_enchant_materials: Dict[str, Any],
    ) -> str:
        parts = self._build_material_parts(drop_materials, drop_enchant_materials)
        return "" if not parts else f"素材: {' / '.join(parts)}"

    def _build_material_parts(
        self,
        drop_materials: Dict[str, Any],
        drop_enchant_materials: Dict[str, Any],
    ) -> List[str]:
        material_parts = [
            f"{label}x{int(drop_materials.get(slot_name, 0))}"
            for slot_name, label in MATERIAL_LABELS.items()
            if int(drop_materials.get(slot_name, 0)) > 0
        ]

        enchant_totals: Dict[str, int] = {}
        for slot_name, label in ENCHANTMENT_MATERIAL_LABELS.items():
            quantity = int(drop_enchant_materials.get(slot_name, 0))
            if quantity <= 0:
                continue
            enchant_totals[label] = enchant_totals.get(label, 0) + quantity

        enchant_parts = [
            f"{label}x{quantity}"
            for label, quantity in enchant_totals.items()
            if quantity > 0
        ]

        return material_parts + enchant_parts

    def _format_area_depth_record_update(self, result: Dict[str, Any]) -> str:
        update = result.get("area_depth_record_update")
        if not isinstance(update, dict):
            return ""

        area_name = str(update.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip() or DEFAULT_AREA
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        display_name = str(update.get("display_name", "") or "").strip() or "?"
        battle_count = max(0, int(update.get("battle_count", 0) or 0))
        total_turns = max(0, int(update.get("total_turns", 0) or 0))

        if bool(update.get("holder_changed", False)):
            previous_display_name = str(update.get("previous_display_name", "") or "").strip()
            if previous_display_name:
                return (
                    f"最深記録交代: {area_name} / {previous_display_name} -> {display_name} / "
                    f"{battle_count}戦 / {total_turns}T"
                )
            return f"最深記録交代: {area_name} / {display_name} / {battle_count}戦 / {total_turns}T"

        if bool(update.get("is_first_record", False)):
            return f"最深記録登録: {area_name} / {display_name} / {battle_count}戦 / {total_turns}T"

        return f"最深記録更新: {area_name} / {display_name} / {battle_count}戦 / {total_turns}T"

    def _build_battle_drop_line(self, battle: Dict[str, Any]) -> str:
        drop_parts: List[str] = []
        drop_items = [
            self.bot.rpg.format_item_brief(item)
            for item in battle.get("drop_items", [])
            if isinstance(item, dict) and item
        ]
        if drop_items:
            drop_parts.append(f"装備 {' / '.join(drop_items)}")

        material_parts = self._build_material_parts(
            battle.get("drop_materials", {}),
            battle.get("drop_enchant_materials", {}),
        )
        if material_parts:
            drop_parts.append(f"素材 {' / '.join(material_parts)}")

        return "" if not drop_parts else f"ドロップ: {' / '.join(drop_parts)}"

    def _format_battle_log_block(self, index: int, battle: Dict[str, Any]) -> str:
        return self._build_single_battle_detail_block(index, battle)

    def _format_battle_summary(self, index: int, battle: Dict[str, Any]) -> str:
        monster = str(battle.get("monster", "?"))
        turns = int(battle.get("turns", 0))
        damage_taken = int(battle.get("damage_taken", 0))

        if monster == "ポーション使用":
            return f"[{index:02d}] 補給 / ポーション使用 / 被ダメ{damage_taken}"

        if battle.get("won", False):
            outcome = "撃破"
        elif battle.get("escaped", False):
            outcome = "離脱"
        else:
            outcome = "敗北"
        return f"[{index:02d}] {monster} / {outcome} / {turns}T / 被ダメ{damage_taken}"

    def _get_actual_battle_logs(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        return get_actual_battle_logs(result)

    def _format_claimed_status_text(self, result: Dict[str, Any]) -> Optional[str]:
        claimed_status = result.get("claimed_status")
        if not isinstance(claimed_status, dict):
            return None

        if bool(claimed_status.get("down", False)):
            status_text = "戦闘不能"
        else:
            hp = int(claimed_status.get("hp", 0))
            max_hp = int(claimed_status.get("max_hp", 0))
            status_text = f"HP {hp}/{max_hp}"

        level_after = result.get("level_after")
        if level_after is None:
            return status_text
        return f"{status_text} / Lv{int(level_after)}"

    def _format_turn_detail_line(self, turn_detail: Dict[str, Any]) -> str:
        turn = max(1, int(turn_detail.get("turn", 1)))
        player_hp_start = int(turn_detail.get("player_hp_start", 0))
        player_hp_end = int(turn_detail.get("player_hp_end", player_hp_start))
        enemy_hp_start = int(turn_detail.get("enemy_hp_start", 0))
        enemy_hp_end = int(turn_detail.get("enemy_hp_end", enemy_hp_start))
        player_action = str(turn_detail.get("player_action", "")).strip()
        enemy_action = str(turn_detail.get("enemy_action", "")).strip()
        action_parts = [
            action
            for action in (player_action, enemy_action)
            if action and action != "行動なし"
        ]
        guarded_note = " / 致死回避発動" if bool(turn_detail.get("guarded", False)) else ""
        line = (
            f"T{turn} | 自分HP {player_hp_start}→{player_hp_end} | "
            f"敵HP {enemy_hp_start}→{enemy_hp_end}"
        )
        if action_parts:
            line += " | " + " / ".join(action_parts)
        if guarded_note:
            line += guarded_note
        return line

    def _format_guard_status(self, guard_count: int) -> str:
        return "あり" if max(0, int(guard_count)) > 0 else "なし"

    def _format_guard_usage(self, guards_used: int, guards_total: int) -> str:
        safe_total = max(0, int(guards_total))
        safe_used = max(0, min(int(guards_used), safe_total))
        if safe_total <= 0:
            return "なし"
        return f"使用 {safe_used}/{safe_total}"

    def _build_single_battle_detail_block(self, index: int, battle: Dict[str, Any]) -> str:
        lines = [self._format_battle_summary(index, battle)]
        turn_details = battle.get("turn_details", [])
        if isinstance(turn_details, list) and turn_details:
            for turn_detail in turn_details:
                if isinstance(turn_detail, dict):
                    lines.append(self._format_turn_detail_line(turn_detail))
        else:
            raw_log_lines = [
                str(log_line).strip()
                for log_line in battle.get("log", [])
                if str(log_line).strip()
            ]
            if raw_log_lines:
                lines.extend(raw_log_lines)
            else:
                lines.append("ターン詳細: なし")

        drop_line = self._build_battle_drop_line(battle)
        if drop_line:
            lines.append(drop_line)
        return "\n".join(lines)

    def _build_exploration_result_lines(
        self,
        display_name: str,
        result: Dict[str, Any],
        *,
        command_name: str,
        detail_state_label: str,
    ) -> List[str]:
        area_name = result.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode = self.bot.rpg.resolve_exploration_mode(result.get("mode"))
        kills: List[Dict[str, Any]] = result.get("kills", [])
        actual_battle_logs = self._get_actual_battle_logs(result)
        drop_items: List[Dict[str, Any]] = result.get("drop_items", [])
        exp_gain = int(result.get("exp", 0))
        gold_gain = int(result.get("gold", 0))
        battle_count = get_battle_count(result)
        total_turns = int(result.get("total_turns", 0))
        exploration_runs = max(1, int(result.get("exploration_runs", 1)))
        hp_after = int(result.get("hp_after", 0))
        potions_used = int(result.get("potions_used", 0))
        auto_potions_bought = int(result.get("auto_potions_bought", 0))
        auto_potion_refill_cost = int(result.get("auto_potion_refill_cost", 0))
        auto_hp_heal_cost = int(result.get("auto_hp_heal_cost", 0))
        auto_hp_restored = int(result.get("auto_hp_restored", 0))
        potions_after_claim = int(result.get("potions_after_claim", 0))
        guards_used = int(result.get("armor_guards_used", 0))
        guards_total = int(result.get("armor_guards_total", 0))
        return_reason = result.get("return_reason", "探索終了")
        downed = bool(result.get("downed", False) or not bool(result.get("returned_safe", True)))
        armor_enchant_consumed = bool(result.get("armor_enchant_consumed", False))
        auto_armor_reenchants = int(result.get("auto_armor_reenchants", 0))
        lines = [
            f"コマンド: {command_name}",
            f"ユーザー: {display_name}",
            f"探索: {mode['label']} / {area_name}",
            f"結果: {'戦闘不能' if downed else '帰還'} / 帰還理由 {return_reason}",
            f"報酬: +{exp_gain}EXP / +{gold_gain}G",
            f"戦績: {battle_count}戦 / {len(kills)}体討伐 / {total_turns}ターン",
            f"生存: HP {hp_after} / ポーション {potions_used} / 致死耐性 {self._format_guard_usage(guards_used, guards_total)}",
        ]
        if exploration_runs > 1:
            lines.insert(3, f"集計: {exploration_runs}回分")

        claimed_status = result.get("claimed_status", {})
        claimed_status_text = self._format_claimed_status_text(result)
        hp_fully_restored = (
            isinstance(claimed_status, dict)
            and not bool(claimed_status.get("down", False))
            and int(claimed_status.get("hp", 0)) >= max(1, int(claimed_status.get("max_hp", 1)))
        )
        if claimed_status_text:
            lines.append(f"現在状態: {claimed_status_text}")

        if auto_potions_bought > 0 or auto_hp_heal_cost > 0:
            return_maintenance_parts: List[str] = []
            if auto_hp_heal_cost > 0:
                if hp_fully_restored:
                    return_maintenance_parts.append(f"HP全快 -{auto_hp_heal_cost}G")
                elif auto_hp_restored > 0:
                    return_maintenance_parts.append(f"HP回復 +{auto_hp_restored} / -{auto_hp_heal_cost}G")
            if auto_potions_bought > 0:
                return_maintenance_parts.append(f"ポーション購入 +{auto_potions_bought}")
            if auto_potion_refill_cost > 0:
                return_maintenance_parts.append(f"-{auto_potion_refill_cost}G")
            return_maintenance_parts.append(f"現在 {potions_after_claim}個")
            lines.append(f"帰還整備: {' / '.join(return_maintenance_parts)}")

        newly_cleared_boss_areas = [
            area_name
            for area_name in result.get("newly_cleared_boss_areas", [])
            if area_name in AREAS
        ]
        if newly_cleared_boss_areas:
            lines.append(f"初回ボス撃破: {' / '.join(newly_cleared_boss_areas)}")

        first_clear_reward_summaries = [
            str(summary).strip()
            for summary in result.get("first_clear_reward_summaries", [])
            if str(summary).strip()
        ]
        if first_clear_reward_summaries:
            lines.append(f"恒久報酬: {' / '.join(first_clear_reward_summaries)}")

        new_records = [
            str(summary).strip()
            for summary in result.get("new_records", [])
            if str(summary).strip()
        ]
        if new_records:
            lines.append(f"記録更新: {' / '.join(new_records)}")

        area_depth_record_update = self._format_area_depth_record_update(result)
        if area_depth_record_update:
            lines.append(area_depth_record_update)

        new_achievements = [
            str(summary).strip()
            for summary in result.get("new_achievements", [])
            if str(summary).strip()
        ]
        if new_achievements:
            lines.append(f"新実績: {' / '.join(new_achievements)}")

        new_titles = [
            str(summary).strip()
            for summary in result.get("new_titles", [])
            if str(summary).strip()
        ]
        if new_titles:
            lines.append(f"新称号: {' / '.join(new_titles)}")

        if auto_armor_reenchants > 0:
            if auto_armor_reenchants > 1:
                lines.append(f"自動整備: 防具に致死回避エンチャを再付与 x{auto_armor_reenchants}")
            else:
                lines.append("自動整備: 防具に致死回避エンチャを再付与")
        elif armor_enchant_consumed:
            lines.append("alert: 致死回避エンチャが今回の探索で消滅")

        if drop_items:
            self._append_chunked_values(
                lines,
                "装備ドロップ",
                [self.bot.rpg.format_item_brief(item) for item in drop_items],
            )
        material_line = self._build_material_line(
            result.get("drop_materials", {}),
            result.get("drop_enchant_materials", {}),
        )
        if material_line:
            lines.append(material_line)

        lines.append("探索要約:")
        lines.append(
            self._build_exploration_detail_summary_message(
                display_name,
                result,
                detail_state_label=detail_state_label,
                total_pages=max(1, battle_count + 1),
                page_label="探索要約",
                truncate=False,
            )
        )
        if actual_battle_logs:
            lines.append("戦闘詳細: ターンごとの詳細は !探索 戦闘")

        return lines

    def _build_recommendation(self, user: Dict[str, Any]) -> Dict[str, Any]:
        builder = getattr(self.bot.rpg, "build_next_recommendation", None)
        if callable(builder):
            recommendation = builder(user)
            if isinstance(recommendation, dict):
                return recommendation
        return {}

    def _build_advice_recommendation(
        self,
        username: str,
        user: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        recommendation = self._build_recommendation(user)
        world_boss_getter = getattr(self.bot.rpg, "get_world_boss_status", None)
        if not callable(world_boss_getter):
            return recommendation, False

        if bool(user.get("down", False)):
            return recommendation, False
        explore = user.get("explore", {})
        if isinstance(explore, dict) and explore.get("state") == "exploring":
            return recommendation, False

        status = world_boss_getter(username)
        if not isinstance(status, dict):
            return recommendation, False
        if str(status.get("phase", "") or "").strip() != "recruiting":
            return recommendation, False
        if status.get("self"):
            return recommendation, False

        boss_name = str(status.get("boss_name", "WB") or "WB").strip() or "WB"
        advice_token = f"{boss_name}:{int(float(status.get('join_ends_at', 0.0) or 0.0))}"
        if str(user.get("last_world_boss_advice_token", "") or "").strip() == advice_token:
            return recommendation, False

        user["last_world_boss_advice_token"] = advice_token
        return (
            {
                "action": "!wb 参加",
                "summary": "!wb 参加 でWBへ合流",
                "reason": f"{boss_name} の募集が始まっているので今だけ参加できます。",
                "area": "",
            },
            True,
        )

    def _format_recommendation_line(self, user: Dict[str, Any]) -> str:
        recommendation = self._build_recommendation(user)
        summary = str(recommendation.get("summary", "") or "").strip()
        reason = str(recommendation.get("reason", "") or "").strip()
        if summary and reason:
            return f"{summary} / {reason}"
        return summary or reason or "おすすめ行動はありません"

    def _get_auto_repeat_progress(self, user: Dict[str, Any]) -> Dict[str, Any]:
        getter = getattr(self.bot.rpg, "get_auto_repeat_progress", None)
        if callable(getter):
            progress = getter(user)
            if isinstance(progress, dict):
                return progress

        feature_unlocks = user.get("feature_unlocks", {})
        unlocked = bool(user.get("auto_explore_stones", 0))
        route_unlocked = False
        if isinstance(feature_unlocks, dict):
            unlocked = unlocked or bool(feature_unlocks.get("auto_repeat", False))
            route_unlocked = bool(feature_unlocks.get("auto_repeat_route", False))
        fragments = max(0, int(user.get("auto_explore_fragments", 0)))
        return {
            "unlocked": unlocked,
            "route_unlocked": route_unlocked,
            "fragments": fragments,
            "required_fragments": 3,
            "remaining_fragments": max(0, 3 - fragments),
        }

    def _get_feature_effect_summaries(self, user: Dict[str, Any]) -> List[str]:
        getter = getattr(self.bot.rpg, "get_feature_effect_summaries", None)
        if callable(getter):
            summaries = getter(user)
            if isinstance(summaries, list):
                return [str(summary).strip() for summary in summaries if str(summary).strip()]
        return []

    def _build_auto_repeat_status_value(self, user: Dict[str, Any]) -> str:
        line = self._build_auto_repeat_unlock_line(user)
        prefix = "自動周回: "
        if line.startswith(prefix):
            return line[len(prefix) :]
        return line

    def _build_result_aggregate_summary(self, result: Dict[str, Any]) -> str:
        run_count = max(0, int(result.get("exploration_runs", 0)))
        battle_count = max(0, int(result.get("battle_count", 0)))
        exp_gain = max(0, int(result.get("exp", 0)))
        gold_gain = max(0, int(result.get("gold", 0)))
        segments = []
        if run_count > 0:
            segments.append(f"{run_count}回")
        if battle_count > 0 or segments:
            segments.append(f"{battle_count}戦")
        segments.append(f"+{exp_gain}EXP")
        segments.append(f"+{gold_gain}G")
        return " / ".join(segments)

    def _build_result_loot_summary(self, result: Dict[str, Any]) -> str:
        synthetic_entry = dict(result)
        synthetic_entry.setdefault(
            "drop_item_count",
            len(result.get("drop_items", [])) if isinstance(result.get("drop_items"), list) else 0,
        )
        return self._build_history_loot_summary(synthetic_entry)

    def _build_auto_repeat_unlock_line(self, user: Dict[str, Any]) -> str:
        progress = self._get_auto_repeat_progress(user)
        if bool(progress.get("unlocked", False)):
            return "自動周回: 解放済み"
        return (
            "自動周回: 未解放 / "
            f"導線:{'済' if bool(progress.get('route_unlocked', False)) else '未'} / "
            f"欠片:{int(progress.get('fragments', 0))}/{int(progress.get('required_fragments', 0))}"
        )

    def _get_area_primary_role(self, area_name: str) -> str:
        area = AREAS.get(area_name, {})
        specialty = str(area.get("specialty", "") or "").strip()
        if specialty:
            return specialty
        if area_name == BEGINNER_GUARANTEE_AREA:
            return "序盤装備"
        if int(area.get("tier", 0) or 0) >= 3:
            return "高レア装備"
        return "通常探索"

    def _get_area_first_clear_reward_summary(self, area_name: str) -> str:
        area = AREAS.get(area_name, {})
        raw_rewards = area.get("first_clear_rewards")
        if not isinstance(raw_rewards, dict):
            return ""

        summary = str(raw_rewards.get("summary", "") or "").strip()
        if summary:
            return summary

        parts: List[str] = []
        raw_unlock_slots = raw_rewards.get("unlock_slots")
        if isinstance(raw_unlock_slots, list):
            slot_labels = [
                SLOT_LABEL.get(str(slot_name).strip(), str(slot_name).strip())
                for slot_name in raw_unlock_slots
                if str(slot_name).strip()
            ]
            slot_labels = [label for label in slot_labels if label]
            if slot_labels:
                parts.append(f"{'・'.join(slot_labels)}スロット解放")

        raw_unlock_features = raw_rewards.get("unlock_features")
        if isinstance(raw_unlock_features, list) and raw_unlock_features:
            feature_labels = [
                FEATURE_UNLOCK_LABELS.get(str(feature_key).strip(), str(feature_key).strip())
                for feature_key in raw_unlock_features
                if str(feature_key).strip()
            ]
            feature_labels = [label for label in feature_labels if label]
            if feature_labels:
                parts.append(" / ".join(feature_labels))

        fragment_count = max(0, int(raw_rewards.get("auto_explore_fragments", 0)))
        if fragment_count > 0:
            parts.append(f"自動周回欠片 +{fragment_count}")

        return " / ".join(parts)

    def _get_claimed_first_clear_reward_areas(self, user: Dict[str, Any]) -> set[str]:
        claimed_reward_areas = user.get("claimed_first_clear_reward_areas", [])
        if not isinstance(claimed_reward_areas, list):
            claimed_reward_areas = []
        claimed = {
            str(area_name).strip()
            for area_name in claimed_reward_areas
            if str(area_name).strip() in AREAS
        }

        boss_clear_areas = user.get("boss_clear_areas", [])
        if isinstance(boss_clear_areas, list):
            claimed.update(
                str(area_name).strip()
                for area_name in boss_clear_areas
                if str(area_name).strip() in AREAS
            )
        return claimed

    def _is_area_first_clear_reward_pending(self, user: Dict[str, Any], area_name: str) -> bool:
        if not self._get_area_first_clear_reward_summary(area_name):
            return False
        return area_name not in self._get_claimed_first_clear_reward_areas(user)

    def _get_prioritized_area_names(self, user: Dict[str, Any]) -> List[str]:
        pending_areas = {
            area_name
            for area_name in AREAS
            if self._is_area_first_clear_reward_pending(user, area_name)
        }
        return sorted(
            list(AREAS.keys()),
            key=lambda area_name: (area_name not in pending_areas,),
        )

    def _build_area_guide_entry(
        self,
        user: Dict[str, Any],
        area_name: str,
        *,
        compact: bool,
    ) -> str:
        role = self._get_area_primary_role(area_name)
        reward_summary = self._get_area_first_clear_reward_summary(area_name)
        reward_pending = self._is_area_first_clear_reward_pending(user, area_name)

        if compact:
            parts = [role]
            if reward_summary:
                status = "未解放" if reward_pending else "解放済"
                parts.append(f"初回:{reward_summary} {status}")
            return f"{area_name}[{' / '.join(parts)}]"

        entry = f"{area_name}: {role}"
        if reward_summary:
            status = "未解放" if reward_pending else "解放済み"
            entry += f" / 初回報酬 {reward_summary} ({status})"
        return entry

    def _build_area_guide_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        lines = [
            "コマンド: !攻略 エリア",
            f"ユーザー: {display_name}",
            "エリア案内:",
        ]
        for area_name in self._get_prioritized_area_names(user):
            lines.append(self._build_area_guide_entry(user, area_name, compact=False))
        lines.append("モード: 慎重=安全重視 / 通常=標準 / 節約=ポーション節約 / 強行=高リスク高報酬")
        return lines

    def _build_recommendation_area_segments(
        self,
        user: Dict[str, Any],
        recommendation: Dict[str, Any],
    ) -> List[str]:
        area_name = str(recommendation.get("area", "") or "").strip()
        if area_name not in AREAS:
            return []

        segments = [f"目的:{self._get_area_primary_role(area_name)}"]
        reward_summary = self._get_area_first_clear_reward_summary(area_name)
        if reward_summary:
            reward_status = "未解放" if self._is_area_first_clear_reward_pending(user, area_name) else "解放済"
            segments.append(f"初回報酬:{reward_summary} {reward_status}")
        return segments

    def _build_slot_unlock_line(self, user: Dict[str, Any]) -> Optional[str]:
        unlocked_slots = getattr(self.bot.rpg, "get_unlocked_slots", None)
        if callable(unlocked_slots):
            slot_state = unlocked_slots(user)
        else:
            slot_state = user.get("slot_unlocks", {})

        locked_labels = []
        if not bool(slot_state.get("armor", False)):
            locked_labels.append("防具")
        if not bool(slot_state.get("ring", False)):
            locked_labels.append("装飾")
        if not locked_labels:
            return None
        reward_summary = self._get_area_first_clear_reward_summary(BEGINNER_GUARANTEE_AREA) or "解放"
        return (
            f"未開放: {'・'.join(locked_labels)} / "
            f"{BEGINNER_GUARANTEE_AREA}ボス初回撃破で {reward_summary}"
        )

    def _build_recommendation_detail_lines(
        self,
        display_name: str,
        user: Dict[str, Any],
        recommendation: Dict[str, Any],
    ) -> List[str]:
        action = str(recommendation.get("action", "") or "").strip() or "!状態"
        summary = str(recommendation.get("summary", "") or "").strip() or "おすすめ行動なし"
        reason = (
            str(recommendation.get("reason", "") or "").strip()
            or "現在の状態から大きな偏りはありません。"
        )
        lines = [
            self._overlay_section("次の一手"),
            self._overlay_kv("コマンド", "!攻略"),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("おすすめ行動", action),
            self._overlay_kv("要約", summary),
            self._overlay_kv("理由", reason),
            self._overlay_section("恒久進行"),
            self._overlay_kv("自動周回", self._build_auto_repeat_status_value(user)),
        ]

        feature_effects = self._get_feature_effect_summaries(user)
        if feature_effects:
            lines.append(self._overlay_kv("恒久効果", " / ".join(feature_effects)))

        slot_unlock_line = self._build_slot_unlock_line(user)
        if slot_unlock_line:
            slot_value = slot_unlock_line.replace("未開放: ", "", 1)
            lines.append(self._overlay_kv("未開放", slot_value))

        area_name = str(recommendation.get("area", "") or "").strip()
        if area_name in AREAS:
            lines.append(self._overlay_section("候補エリア"))
            lines.append(self._overlay_kv("エリア", area_name))
            lines.append(self._overlay_kv("用途", self._get_area_primary_role(area_name)))
            reward_summary = self._get_area_first_clear_reward_summary(area_name)
            if reward_summary:
                reward_status = (
                    "未解放"
                    if self._is_area_first_clear_reward_pending(user, area_name)
                    else "解放済"
                )
                lines.append(
                    self._overlay_kv("初回報酬", f"{reward_summary} {reward_status}")
                )

        return [line for line in lines if line]

    def _summarize_history(self, history: List[Dict[str, Any]]) -> Dict[str, int]:
        auto_repeat_entries = [
            entry for entry in history if max(1, int(entry.get("exploration_runs", 1))) > 1
        ]
        return {
            "entry_count": len(history),
            "total_runs": sum(max(1, int(entry.get("exploration_runs", 1))) for entry in history),
            "total_battles": sum(max(0, int(entry.get("battle_count", 0))) for entry in history),
            "total_exp": sum(max(0, int(entry.get("exp", 0))) for entry in history),
            "total_gold": sum(max(0, int(entry.get("gold", 0))) for entry in history),
            "auto_repeat_entries": len(auto_repeat_entries),
            "auto_repeat_runs": sum(
                max(1, int(entry.get("exploration_runs", 1))) for entry in auto_repeat_entries
            ),
            "auto_repeat_battles": sum(
                max(0, int(entry.get("battle_count", 0))) for entry in auto_repeat_entries
            ),
            "auto_repeat_exp": sum(max(0, int(entry.get("exp", 0))) for entry in auto_repeat_entries),
            "auto_repeat_gold": sum(max(0, int(entry.get("gold", 0))) for entry in auto_repeat_entries),
            "best_auto_repeat_runs": max(
                [max(1, int(entry.get("exploration_runs", 1))) for entry in auto_repeat_entries],
                default=0,
            ),
        }

    def _build_history_detail_lines(
        self,
        display_name: str,
        history: List[Dict[str, Any]],
    ) -> List[str]:
        summary = self._summarize_history(history)
        lines = [
            self._overlay_section("履歴概要"),
            self._overlay_kv("コマンド", "!探索 履歴"),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("件数", f"{summary['entry_count']}件"),
            self._overlay_kv(
                "合計",
                (
                    f"{summary['total_runs']}回 / {summary['total_battles']}戦 / "
                    f"+{summary['total_exp']}EXP / +{summary['total_gold']}G"
                ),
            ),
        ]

        if summary["auto_repeat_entries"] > 0:
            lines.extend(
                [
                    self._overlay_section("自動周回集計"),
                    self._overlay_kv("セッション", f"{summary['auto_repeat_entries']}件"),
                    self._overlay_kv(
                        "合計",
                        (
                            f"{summary['auto_repeat_runs']}回 / {summary['auto_repeat_battles']}戦 / "
                            f"+{summary['auto_repeat_exp']}EXP / +{summary['auto_repeat_gold']}G"
                        ),
                    ),
                    self._overlay_kv("最大連続", f"{summary['best_auto_repeat_runs']}回分"),
                ]
            )

        lines.append(self._overlay_section("履歴一覧"))
        for index, entry in enumerate(history, start=1):
            entry_kind = "自動周回" if max(1, int(entry.get("exploration_runs", 1))) > 1 else "探索"
            lines.append(
                self._overlay_kv(
                    f"{index}. {entry_kind}",
                    self._build_history_entry_line(entry),
                )
            )

        return [line for line in lines if line]

    def _build_organize_detail_lines(
        self,
        *,
        command_label: str,
        display_name: str,
        before_power: int,
        after_power: int,
        before_bag_count: int,
        after_bag_count: int,
        before_weapon: str,
        after_weapon: str,
        before_armor: str,
        after_armor: str,
        before_ring: str,
        after_ring: str,
        before_shoes: str,
        after_shoes: str,
        sold_count: int,
        gold: int,
        recommendation_summary: str,
        has_changes: bool,
    ) -> List[str]:
        status_text = "更新あり" if has_changes else "変化なし"
        return [
            self._overlay_section("整理結果"),
            self._overlay_kv("コマンド", command_label),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("状態", status_text),
            self._overlay_kv("戦力", f"{before_power} -> {after_power}"),
            self._overlay_kv("売却", f"{sold_count}個 / +{gold}G"),
            self._overlay_kv("バッグ", f"{before_bag_count}件 -> {after_bag_count}件"),
            self._overlay_section("装備更新"),
            self._overlay_kv("武器", f"{before_weapon} -> {after_weapon}"),
            self._overlay_kv("防具", f"{before_armor} -> {after_armor}"),
            self._overlay_kv("装飾", f"{before_ring} -> {after_ring}"),
            self._overlay_kv("靴", f"{before_shoes} -> {after_shoes}"),
            self._overlay_section("次の行動"),
            self._overlay_kv("おすすめ", recommendation_summary),
        ]

    def _format_material_transition_summary(
        self,
        before_materials: Dict[str, int],
        after_materials: Dict[str, int],
        *,
        target_slots: List[str],
    ) -> str:
        segments = []
        for slot_name in target_slots:
            label = MATERIAL_LABELS.get(slot_name, slot_name)
            segments.append(
                f"{label} {max(0, int(before_materials.get(slot_name, 0)))}"
                f" -> {max(0, int(after_materials.get(slot_name, 0)))}"
            )
        return " / ".join(segments) if segments else "変化なし"

    def _build_auto_enhance_detail_lines(
        self,
        *,
        command_label: str,
        display_name: str,
        before_power: int,
        after_power: int,
        before_gold: int,
        after_gold: int,
        before_weapon: str,
        after_weapon: str,
        before_armor: str,
        after_armor: str,
        before_ring: str,
        after_ring: str,
        before_shoes: str,
        after_shoes: str,
        summary: Dict[str, Any],
    ) -> List[str]:
        target_slots = [slot for slot in summary.get("target_slots", []) if slot in SLOT_LABEL]
        slot_summary = " / ".join(SLOT_LABEL.get(slot, slot) for slot in target_slots) or "なし"
        before_materials = summary.get("before_materials", {})
        after_materials = summary.get("after_materials", {})
        lines = [
            self._overlay_section("自動強化"),
            self._overlay_kv("コマンド", command_label),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("対象", slot_summary),
            self._overlay_kv(
                "結果",
                (
                    f"{max(0, int(summary.get('attempt_count', 0)))}回 / "
                    f"成功 {max(0, int(summary.get('success_count', 0)))} / "
                    f"失敗 {max(0, int(summary.get('failure_count', 0)))}"
                ),
            ),
            self._overlay_kv("戦力", f"{before_power} -> {after_power}"),
            self._overlay_kv("所持金", f"{before_gold}G -> {after_gold}G"),
            self._overlay_kv(
                "素材",
                self._format_material_transition_summary(
                    before_materials,
                    after_materials,
                    target_slots=target_slots,
                ),
            ),
            self._overlay_section("装備"),
            self._overlay_kv("武器", f"{before_weapon} -> {after_weapon}"),
            self._overlay_kv("防具", f"{before_armor} -> {after_armor}"),
            self._overlay_kv("装飾", f"{before_ring} -> {after_ring}"),
            self._overlay_kv("靴", f"{before_shoes} -> {after_shoes}"),
        ]

        attempt_logs = [
            attempt
            for attempt in summary.get("attempt_logs", [])
            if isinstance(attempt, dict)
        ]
        if attempt_logs:
            lines.append(self._overlay_section("試行ログ"))
            for index, attempt in enumerate(attempt_logs, start=1):
                slot_name = str(attempt.get("slot", "") or "").strip()
                slot_label = SLOT_LABEL.get(slot_name, slot_name or "?")
                lines.append(
                    self._overlay_kv(
                        f"{index}. {slot_label}",
                        str(attempt.get("message", "") or "").strip() or "結果なし",
                    )
                )

        stop_reasons = {
            str(slot_name).strip(): str(reason).strip()
            for slot_name, reason in dict(summary.get("stop_reasons", {})).items()
            if str(slot_name).strip() in SLOT_LABEL and str(reason).strip()
        }
        if stop_reasons:
            lines.append(self._overlay_section("停止理由"))
            for slot_name in target_slots:
                reason = stop_reasons.get(slot_name)
                if not reason:
                    continue
                lines.append(self._overlay_kv(SLOT_LABEL.get(slot_name, slot_name), reason))

        return [line for line in lines if line]

    def _build_auto_enhance_reply_message(
        self,
        display_name: str,
        summary: Dict[str, Any],
        *,
        before_power: int,
        after_power: int,
    ) -> str:
        attempt_count = max(0, int(summary.get("attempt_count", 0)))
        success_count = max(0, int(summary.get("success_count", 0)))
        failure_count = max(0, int(summary.get("failure_count", 0)))
        if attempt_count > 0:
            return self._build_detail_hint_reply(
                display_name,
                f"自動強化 {attempt_count}回",
                f"成功{success_count}",
                f"失敗{failure_count}",
                f"戦力{before_power}->{after_power}",
            )

        stop_reasons = [
            str(reason).strip()
            for reason in dict(summary.get("stop_reasons", {})).values()
            if str(reason).strip()
        ]
        reason_summary = stop_reasons[0] if stop_reasons else "強化できる装備がありません"
        return self._build_detail_hint_reply(display_name, "自動強化 0回", reason_summary)

    def _get_default_diagnosis_request(self, user: Dict[str, Any]) -> str:
        explore = user.get("explore", {})
        if isinstance(explore, dict) and explore.get("state") == "exploring":
            area_name = str(explore.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip()
            if area_name in AREAS:
                mode = self.bot.rpg.resolve_exploration_mode(explore.get("mode"))
                return f"{mode['label']} {area_name}"

        recommendation = self._build_recommendation(user)
        area_name = str(recommendation.get("area", "") or "").strip()
        if area_name in AREAS:
            return area_name
        return DEFAULT_AREA

    def _format_diagnosis_stage_line(self, stage: Dict[str, Any]) -> str:
        estimate = stage.get("estimate", {})
        risk = stage.get("risk", {})
        monster = stage.get("monster", {})
        start_hp = max(1, int(stage.get("start_hp", 1)))
        predicted_damage = max(0, int(estimate.get("predicted_damage", 0)))
        hp_after = max(0, int(estimate.get("player_hp_after", 0)))
        turns = max(0, int(estimate.get("turns_to_kill_enemy", estimate.get("turns", 0))))
        potions_used = max(0, int(estimate.get("potions_used", 0)))
        guards_used = max(0, int(estimate.get("guards_used", 0)))
        notes: List[str] = []
        if not bool(estimate.get("can_win", False)):
            notes.append("撃破不可想定")
        elif turns > 0:
            notes.append(f"{turns}T")
        if potions_used > 0:
            notes.append(f"P{potions_used}")
        if guards_used > 0:
            notes.append(f"G{guards_used}")
        note_text = "" if not notes else " / " + " / ".join(notes)
        return (
            f"{stage.get('label', '?')}: {risk.get('label', '安定')} / "
            f"第{int(stage.get('battle_number', 0))}戦 {monster.get('name', '?')} / "
            f"開始HP {start_hp} / 被ダメ {predicted_damage} / 残HP {hp_after}{note_text}"
        )

    def _build_exploration_diagnosis_lines(
        self,
        display_name: str,
        user: Dict[str, Any],
        diagnosis: Dict[str, Any],
    ) -> List[str]:
        mode = diagnosis.get("mode") or self.bot.rpg.resolve_exploration_mode(None)
        area_name = str(diagnosis.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip()
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        player = diagnosis.get("player", {})
        reward = diagnosis.get("reward_estimate", {})
        lines = [
            "コマンド: !攻略 診断",
            f"ユーザー: {display_name}",
            f"対象: {mode['label']} / {area_name}",
            (
                f"戦力: HP {int(player.get('hp', 0))}/{int(player.get('max_hp', DEFAULT_MAX_HP))}"
                f" / A {int(player.get('atk', 0))} / D {int(player.get('def', 0))}"
                f" / ポーション {int(player.get('potions', 0))}"
                f" / 致死耐性 {self._format_guard_status(int(player.get('guards', 0)))}"
            ),
            (
                f"想定危険度: {diagnosis.get('danger_label', '安定')} / "
                f"{diagnosis.get('danger_reason', '大崩れしにくい')}"
            ),
            (
                f"目安: {int(reward.get('encounters_min', 0))}-{int(reward.get('encounters_max', 0))}戦"
                f" / 1戦平均 +{int(reward.get('avg_exp', 0))}EXP"
                f" / +{int(reward.get('avg_gold', 0))}G"
                f" / 装備率 約{int(reward.get('avg_drop_rate_pct', 0))}%"
            ),
            "想定遭遇:",
        ]
        for stage in diagnosis.get("stages", []):
            if isinstance(stage, dict):
                lines.append(self._format_diagnosis_stage_line(stage))

        lines.append(f"用途: {self._build_area_guide_entry(user, area_name, compact=False)}")
        recommendation = self._build_recommendation(user)
        if str(recommendation.get("area", "") or "").strip() == area_name:
            reason = str(recommendation.get("reason", "") or "").strip()
            if reason:
                lines.append(f"補足: {reason}")
        return lines

    def _build_exploration_diagnosis_reply(
        self,
        display_name: str,
        user: Dict[str, Any],
        diagnosis: Dict[str, Any],
    ) -> str:
        mode = diagnosis.get("mode") or self.bot.rpg.resolve_exploration_mode(None)
        area_name = str(diagnosis.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip()
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        reward = diagnosis.get("reward_estimate", {})
        role = self._get_area_primary_role(area_name)
        reply_segments = [
            f"{display_name} 攻略診断",
            f"{mode['label']} {area_name}",
            f"危険度:{diagnosis.get('danger_label', '安定')}",
            f"目安:{int(reward.get('encounters_min', 0))}-{int(reward.get('encounters_max', 0))}戦",
            (
                f"期待:1戦平均 約{int(reward.get('avg_exp', 0))}EXP "
                f"約{int(reward.get('avg_gold', 0))}G 装備率{int(reward.get('avg_drop_rate_pct', 0))}%"
            ),
            f"用途:{role}",
        ]
        reward_summary = self._get_area_first_clear_reward_summary(area_name)
        if reward_summary and self._is_area_first_clear_reward_pending(user, area_name):
            reply_segments.append(f"初回:{reward_summary}")
        return self._truncate_chat_text(" / ".join(reply_segments))

    def _build_history_entry_line(self, entry: Dict[str, Any], *, include_loot: bool = True) -> str:
        mode = self.bot.rpg.resolve_exploration_mode(entry.get("mode"))
        area_name = entry.get("area", DEFAULT_AREA)
        result_label = "戦闘不能" if bool(entry.get("downed", False)) else "帰還"
        segments = [
            f"{mode['label']} {area_name}",
            result_label,
            f"{int(entry.get('battle_count', 0))}戦",
            f"+{int(entry.get('exp', 0))}EXP",
            f"+{int(entry.get('gold', 0))}G",
        ]
        if int(entry.get("exploration_runs", 1)) > 1:
            segments.insert(0, f"{int(entry.get('exploration_runs', 1))}回分")
        if include_loot:
            loot_summary = self._build_history_loot_summary(entry)
            if loot_summary:
                segments.append(f"戦利品:{loot_summary}")
        return " / ".join(segments)

    def _build_history_loot_summary(self, entry: Dict[str, Any]) -> str:
        drop_items = entry.get("drop_items", [])
        if isinstance(drop_items, list) and drop_items:
            preview = " / ".join(
                self.bot.rpg.format_item_brief(item)
                for item in drop_items[:2]
                if isinstance(item, dict)
            )
            extra_count = max(0, int(entry.get("drop_item_count", len(drop_items))) - min(2, len(drop_items)))
            if extra_count > 0:
                preview += f" / ...他{extra_count}件"
            return preview

        material_summary = self._build_material_line(
            entry.get("drop_materials", {}),
            entry.get("drop_enchant_materials", {}),
        )
        if material_summary:
            return material_summary

        if int(entry.get("auto_explore_stones", 0)) > 0:
            return AUTO_EXPLORE_STONE_NAME
        return ""

    def _resolve_bag_reference(
        self,
        user: Dict[str, Any],
        reference_text: Optional[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        safe_reference = nfkc(reference_text or "").strip()
        if not safe_reference:
            return None, "バッグ番号か item_id を指定してください。"

        sorted_bag = self.bot.rpg.get_sorted_bag_items(user)
        if safe_reference.isdigit():
            index = int(safe_reference)
            if index <= 0 or index > len(sorted_bag):
                return None, f"バッグ番号は 1 から {len(sorted_bag)} の範囲で指定してください。"
            return sorted_bag[index - 1], None

        for item in sorted_bag:
            if str(item.get("item_id", "") or "").strip() == safe_reference:
                return item, None

        equipped = user.get("equipped", {})
        if isinstance(equipped, dict):
            for item in equipped.values():
                if not isinstance(item, dict):
                    continue
                if str(item.get("item_id", "") or "").strip() == safe_reference:
                    return item, None
        return None, "指定した装備が見つかりません。 `!装備 バッグ` で番号か item_id を確認してください。"

    def _build_inventory_detail_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        bag = self.bot.rpg.get_sorted_bag_items(user)
        lines = [
            "コマンド: !装備 バッグ",
            f"ユーザー: {display_name}",
            f"件数: {len(bag)}件",
        ]
        if not bag:
            lines.append("バッグ: 空です")
            lines.append(f"素材: {self.bot.rpg.format_material_inventory(user)}")
            return lines

        for index, item in enumerate(bag[:20], start=1):
            protected = " [保護]" if self.bot.rpg.is_item_protected(user, item) else ""
            item_id = str(item.get("item_id", "") or "").strip()
            lines.append(
                f"{index}: {self.bot.rpg.format_item_brief(item)}{protected} / id:{item_id}"
            )
        if len(bag) > 20:
            lines.append(f"...他{len(bag) - 20}件")
        lines.append(f"素材: {self.bot.rpg.format_material_inventory(user)}")
        return lines

    def _build_me_detail_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        level = self.bot.rpg.get_adventure_level(user)
        gold = int(user.get("gold", 0))
        hp = int(user.get("hp", DEFAULT_MAX_HP))
        max_hp = int(user.get("max_hp", DEFAULT_MAX_HP))
        potions = int(user.get("potions", 0))
        auto_potion_target = self.bot.rpg.get_auto_potion_refill_target(user)
        explore = user.get("explore", {})
        mode_key = explore.get("mode") if explore.get("state") == "exploring" else None
        active_mode = self.bot.rpg.resolve_exploration_mode(mode_key)
        atk, defense = self.bot.rpg.get_player_combat_stats(user, active_mode["key"])
        speed = getattr(self.bot.rpg, "get_player_speed", lambda _user: 0)(user)
        active_title_label = self._get_active_title_label(user)
        titled_display_name = self._format_titled_display_name(display_name, active_title_label)
        auto_potion_label = (
            "OFF"
            if auto_potion_target <= 0
            else f"{auto_potion_target}個維持"
        )

        lines = [
            "コマンド: !状態",
            f"ユーザー: {titled_display_name}",
            f"プロフィール: Lv{level} / 所持金{gold}G",
            f"称号: {active_title_label or 'なし'} / 実績 {self._get_achievement_count(user)}件",
            f"戦闘力: HP {hp}/{max_hp} / A {atk} / D {defense} / S {speed} / ポーション {potions}",
            f"補給設定: 自動補充 {auto_potion_label} / 上限 {MAX_POTIONS_PER_EXPLORATION}個",
            f"装備: {self._format_equipment_summary(user)}",
            f"効果: 武器 {self._format_weapon_bonus(user)} / 装飾 {self._format_ring_bonus(user)}",
            f"パッシブ: {self._format_skill_slot_summary(user, 'passive')}",
            f"アクティブ: {self._format_skill_slot_summary(user, 'active')}",
            f"素材: {self.bot.rpg.format_material_inventory(user)}",
            f"致死耐性: {self._format_guard_status_for_user(user)}",
            f"おすすめ: {self._format_recommendation_line(user)}",
            self._build_auto_repeat_unlock_line(user),
        ]

        feature_effects = self._get_feature_effect_summaries(user)
        if feature_effects:
            lines.append(f"恒久効果: {' / '.join(feature_effects)}")

        slot_unlock_line = self._build_slot_unlock_line(user)
        if slot_unlock_line:
            lines.append(slot_unlock_line)

        if user.get("down", False):
            lines.append("状態: 戦闘不能 / !蘇生 で復帰可能")
            return lines

        if explore.get("state") != "exploring":
            lines.append("探索: 待機中")
            return lines

        remain = int(explore.get("ends_at", 0) - now_ts())
        area_name = explore.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode = self.bot.rpg.resolve_exploration_mode(explore.get("mode"))
        auto_repeat_active = bool(explore.get("auto_repeat", False))
        aggregate_result = user.get("auto_repeat_result")
        if auto_repeat_active:
            if remain > 0:
                lines.append(
                    f"探索: {mode['label']} / {area_name} / 残り {self.bot.rpg.format_duration(remain)}"
                )
            else:
                lines.append(f"探索: {mode['label']} / {area_name} / 継続中")
            if isinstance(aggregate_result, dict):
                aggregate_summary = self._build_result_aggregate_summary(aggregate_result)
                if aggregate_summary:
                    lines.append(f"集計中: {aggregate_summary}")
                loot_summary = self._build_result_loot_summary(aggregate_result)
                if loot_summary:
                    lines.append(f"主な戦利品: {loot_summary}")
            return lines

        if remain > 0:
            lines.append(
                f"探索: {mode['label']} / {area_name} / 残り {self.bot.rpg.format_duration(remain)}"
            )
            return lines

        lines.append(f"探索: 完了済み / {mode['label']} / {area_name} / !探索 結果 で受け取り")
        result = explore.get("result") or {}
        preview_lines = self._build_exploration_result_lines(
            display_name,
            result,
            command_name="!探索 結果",
            detail_state_label="受取待ち",
        )
        lines.extend(preview_lines[2:])
        return lines

    def _format_unique_label_summary(self, labels: Dict[str, str]) -> str:
        ordered_labels: List[str] = []
        seen = set()
        for slot_name in self._get_slot_order():
            label = str(labels.get(slot_name, "")).strip()
            if not label or label in seen:
                continue
            ordered_labels.append(label)
            seen.add(label)
        return " / ".join(ordered_labels) if ordered_labels else "なし"

    def _build_mode_help_summary(self) -> str:
        mode_notes = {
            "cautious": "安全重視",
            "normal": "標準",
            "saving": "ポーション節約",
            "reckless": "高リスク高報酬",
        }
        parts: List[str] = []
        for mode_key in ("cautious", "normal", "saving", "reckless"):
            config = EXPLORATION_MODE_CONFIG.get(mode_key, {})
            label = str(config.get("label", mode_key))
            parts.append(f"{label}:{mode_notes.get(mode_key, '標準')}")
        return " / ".join(parts)

    def _build_rpg_help_lines(self) -> List[str]:
        enhancement_materials = self._format_unique_label_summary(MATERIAL_LABELS)
        enchantment_materials = self._format_unique_label_summary(ENCHANTMENT_MATERIAL_LABELS)
        default_mode = self.bot.rpg.resolve_exploration_mode(DEFAULT_EXPLORATION_MODE)
        return [
            "コマンド: !ヘルプ",
            "基本の流れ:",
            "1. !状態 で自分の状態を確認",
            "2. !攻略 エリア で行き先を見る",
            f"3. !探索 開始 {BEGINNER_GUARANTEE_AREA} で出発",
            "4. 終わったら !探索 結果 で受け取り",
            "5. !装備 整理 で装備更新と不要装備売却",
            f"6. HPが不安なら !状態 ポーション で補充 ({POTION_PRICE}G)",
            "よく使うコマンド:",
            "!状態 / !探索 / !装備 / !スキル / !称号 / !攻略 / !wb / !discord",
            f"!探索 {BEGINNER_GUARANTEE_AREA} / !探索 慎重 {BEGINNER_GUARANTEE_AREA} / !探索 自動 {BEGINNER_GUARANTEE_AREA}",
            "!探索 結果 / !探索 前回 / !探索 履歴 / !探索 戦利品",
            "!探索 戦闘 / !探索 戦闘 3 / !探索 準備 武器 / !攻略 診断 慎重 朝の森",
            "!装備 バッグ / !装備 素材 / !装備 整理",
            "!装備 強化 武器 / !装備 自動強化 / !装備 エンチャント 武器",
            "!スキル / !スキル 強化 鉄壁 / !スキル 変更 ドルマダキア",
            "!称号 / !称号 森を越えし者 / !称号 解除",
            "!wb / !wb 参加 / !wb 結果 / !wb ランキング",
            "!discord / !参加URL / !招待",
            "!wb ショップ / !wb 交換 闘気",
            "!状態 蘇生 / !装備 保護 1 / !装備 保護解除 1",
            "探索モード:",
            self._build_mode_help_summary(),
            "育成のポイント:",
            f"強化には {enhancement_materials} を使う",
            f"エンチャントには {enchantment_materials} を使う",
            (
                f"{BEGINNER_GUARANTEE_AREA} は序盤向け。"
                f"Lv{BEGINNER_GUARANTEE_MAX_LEVEL} までは不足装備を揃えやすい"
            ),
            (
                f"入力例: !探索 {default_mode['label']} {BEGINNER_GUARANTEE_AREA} / "
                f"!探索 慎重 {BEGINNER_GUARANTEE_AREA}"
            ),
            (
                "自動周回は 星影の祭壇導線解放 + 欠片3個 で "
                f"!探索 自動 {default_mode['label']} {BEGINNER_GUARANTEE_AREA}"
            ),
            f"後方互換: !探索開始 自動 {BEGINNER_GUARANTEE_AREA} も利用可能",
            "!攻略 は今のおすすめ行動、!攻略 順 は固定の攻略目安",
        ]

    def _build_status_help_lines(self) -> List[str]:
        return [
            "コマンド: !状態",
            "主要サブコマンド:",
            "!状態",
            "!状態 HP / !状態 EXP",
            "!状態 ポーション",
            "!状態 ポーション 5 / !状態 ポーション 0",
            "!状態 蘇生",
            "!称号",
            "旧 !me / !hp / !exp / !ポーション購入 / !蘇生 も利用可能",
        ]

    def _build_explore_help_lines(self) -> List[str]:
        default_mode = self.bot.rpg.resolve_exploration_mode(DEFAULT_EXPLORATION_MODE)
        return [
            "コマンド: !探索",
            "主要サブコマンド:",
            f"!探索 {BEGINNER_GUARANTEE_AREA}",
            f"!探索 慎重 {BEGINNER_GUARANTEE_AREA}",
            f"!探索 開始 {BEGINNER_GUARANTEE_AREA}",
            f"!探索 開始 {default_mode['label']} {BEGINNER_GUARANTEE_AREA}",
            "!探索 準備 武器",
            f"!探索 自動 {default_mode['label']} {BEGINNER_GUARANTEE_AREA}",
            "!探索 停止",
            "!探索 結果 / !探索 前回 / !探索 履歴 / !探索 戦利品",
            "!探索 戦闘 / !探索 戦闘 3",
            "エリア確認と診断は !攻略 エリア / !攻略 診断 を使います",
        ]

    def _build_equip_help_lines(self) -> List[str]:
        return [
            "コマンド: !装備",
            "主要サブコマンド:",
            "!装備",
            "!装備 バッグ / !装備 素材 / !装備 整理",
            "!装備 保護 1 / !装備 保護解除 1",
            "!装備 強化 武器 / !装備 自動強化 / !装備 エンチャント 武器",
            "旧 !バッグ / !素材 / !整理 / !強化 / !自動強化 / !エンチャント も利用可能",
        ]

    def _build_skill_help_lines(self) -> List[str]:
        return [
            "コマンド: !スキル",
            "主要サブコマンド:",
            "!スキル",
            "!スキル 強化 鉄壁",
            "!スキル 変更 ドルマダキア",
            "!スキル 変更 パッシブ 疾風",
            "!スキル変更 パッシブ 1 闘魂 2 鉄壁 3 迅雷",
            "!スキル変更 アクティブ 1 星導 2 破城一閃",
            "旧 !スキル強化 / !スキル変更 も利用可能",
        ]

    def _build_title_help_lines(self) -> List[str]:
        return [
            "コマンド: !称号",
            "主要サブコマンド:",
            "!称号",
            "!称号 森を越えし者",
            "!称号 解除",
            "!称号 変更 森を越えし者",
            "!称号 変更 解除",
            "称号は実績解放で増えます",
        ]

    def _build_advice_help_lines(self) -> List[str]:
        return [
            "コマンド: !攻略",
            "主要サブコマンド:",
            "!攻略",
            "!攻略 順",
            "!攻略 診断 慎重 朝の森",
            "!攻略 エリア",
            "旧 !攻略順 / !探索診断 / !探索地 も利用可能",
        ]

    def _build_world_boss_help_lines(self) -> List[str]:
        summon_cost = self._get_world_boss_summon_material_cost()
        summon_line = "!wb 召喚"
        if summon_cost > 0:
            summon_line = f"!wb 召喚 (強化素材合計 {summon_cost})"
        debug_entries = self._get_world_boss_selector_entries()
        debug_line = ""
        if debug_entries:
            debug_examples = " / ".join(f"!wb {index}" for index, _, _ in debug_entries[:4])
            debug_line = f"デバッグ用(配信者のみ): {debug_examples} / !wb終了"
        lines = [
            "コマンド: !wb",
            "主要サブコマンド:",
            "!wb",
            f"{summon_line} / !wb 参加 / !wb 離脱",
            "!wb 結果 / !wb ランキング",
            "!wb ショップ / !wb 交換 闘気",
            "配信者操作: !wb 開始 / !wb スキップ",
            debug_line,
            "旧 !wb召喚 / !wb参加 / !wbショップ / !wb交換 も利用可能",
        ]
        return [line for line in lines if line]

    def _build_manage_help_lines(self) -> List[str]:
        return [
            "コマンド: !管理",
            "配信者用サブコマンド:",
            "!管理 読み上げID 3",
            "!管理 読み上げ話者 ずんだもん",
            "!管理 debug heal alice",
            "!管理 debug gold 100 alice",
            "旧 !読み上げID / !読み上げ話者 / !debuggold も利用可能",
        ]

    def _build_discord_help_lines(self) -> List[str]:
        invite_url = self._get_discord_invite_url()
        lines = [
            "コマンド: !discord",
            "主な使い方:",
            "!discord",
            "!discord help",
            "!参加URL / !招待 / !ディスコード も利用可能",
        ]
        if invite_url:
            lines.append(f"現在の参加URL: {invite_url}")
        else:
            lines.append("現在の参加URL: 未設定")
            lines.append("配信者が DISCORD_INVITE_URL を設定すると表示できます")
        return lines

    def _build_progression_help_lines(self) -> List[str]:
        weapon_material = MATERIAL_LABELS.get("weapon", "武器素材")
        armor_material = MATERIAL_LABELS.get("armor", "防具素材")
        ring_material = MATERIAL_LABELS.get("ring", "装飾素材")
        shoes_material = MATERIAL_LABELS.get("shoes", "靴素材")
        enchantment_materials = self._format_unique_label_summary(ENCHANTMENT_MATERIAL_LABELS)
        return [
            "コマンド: !攻略 順",
            "おすすめ攻略順:",
            (
                f"1. {BEGINNER_GUARANTEE_AREA}: 序盤の起点。"
                f"初回ボス撃破で防具・装飾・靴解放。まずは装備を揃えて !装備 整理"
            ),
            f"2. 三日月廃墟: {enchantment_materials} 集め。エンチャントの準備",
            "3. ヘッセ深部: 高レア装備を狙って戦力更新",
            f"4. 紅蓮の鉱山: {weapon_material} 集め。火力不足ならここを優先",
            f"5. 沈黙の城塞跡: {armor_material} 集め。倒されるならここを優先",
            f"6. 星影の祭壇: {ring_material} 集め。装飾強化と自動周回導線解放",
            f"7. 迅雷の断崖: {shoes_material} 集め。靴を詰める終盤の特化周回",
            "進め方のコツ:",
            "!探索 結果 -> !装備 整理 を毎回回す",
            "勝てない時は 慎重、安定したら 通常、背伸びしたい時だけ 強行",
            "素材集めは特化地、レア装備掘りは ヘッセ深部 を使い分ける",
            "戦闘不能が増えたら ポーション補充 と 防具強化 を優先",
            "自動周回は ヘッセ/紅蓮/沈黙 の欠片3個 + 星影の導線解放 で開始可能",
            "周回の目安: 朝の森 -> 三日月廃墟 -> ヘッセ深部 -> 紅蓮/沈黙 -> 星影 -> 迅雷",
        ]

    def _build_world_boss_ranking_summary(self, ranking: List[Dict[str, Any]]) -> str:
        if not ranking:
            return "なし"
        parts = []
        for entry in ranking[:5]:
            rank = max(1, int(entry.get("rank", 0)))
            name = str(entry.get("display_name", "?") or "?").strip() or "?"
            title_label = str(entry.get("title_label", "") or "").strip()
            name = self._format_titled_display_name(name, title_label)
            contribution_score = max(
                0,
                int(entry.get("total_contribution_score", entry.get("contribution_score", 0)) or 0),
            )
            parts.append(f"#{rank} {name} 貢献{contribution_score}")
        return " / ".join(parts)

    def _format_world_boss_contribution_breakdown(self, payload: Dict[str, Any]) -> str:
        contribution = payload.get("contribution", {})
        if not isinstance(contribution, dict):
            contribution = {}
        damage_score = max(0, int(contribution.get("damage_score", 0) or 0))
        support_score = max(0, int(contribution.get("support_score", 0) or 0))
        survival_score = max(0, int(contribution.get("survival_score", 0) or 0))
        objective_score = max(0, int(contribution.get("objective_score", 0) or 0))
        return (
            f"攻 {damage_score} / "
            f"支 {support_score} / "
            f"生 {survival_score} / "
            f"目 {objective_score}"
        )

    def _get_world_boss_summon_material_cost(self) -> int:
        getter = getattr(self.bot.rpg, "get_world_boss_summon_material_cost", None)
        if not callable(getter):
            return 0
        try:
            return max(0, int(getter() or 0))
        except (TypeError, ValueError):
            return 0

    def _build_world_boss_status_lines(self, display_name: str, status: Dict[str, Any]) -> List[str]:
        phase = str(status.get("phase", "idle") or "idle").strip()
        boss = status.get("boss", {})
        boss_name = str(boss.get("name", "WB") or "WB").strip() or "WB"
        boss_title = str(boss.get("title", "") or "").strip()
        phase_label = str(status.get("phase_label", "") or "").strip()
        event_text = str(status.get("event_text", "") or "").strip()
        leader_name = str(status.get("leader_name", "") or "").strip()
        leader_score = max(0, int(status.get("leader_score", 0) or 0))
        runner_up_name = str(status.get("runner_up_name", "") or "").strip()
        runner_up_score = max(0, int(status.get("runner_up_score", 0) or 0))
        leader_gap = max(0, int(status.get("leader_gap", 0) or 0))
        race_focus_active = bool(status.get("race_focus_active", False))
        ranking = [
            entry
            for entry in status.get("ranking", [])
            if isinstance(entry, dict)
        ]
        recent_logs = [
            str(line).strip()
            for line in status.get("recent_logs", [])
            if str(line).strip()
        ]

        lines = [
            self._overlay_section("ワールドボス"),
            self._overlay_kv("コマンド", "!wb"),
            self._overlay_kv("ユーザー", display_name),
        ]

        if phase == "idle":
            lines.append(self._overlay_kv("状態", "待機中"))
            summon_cost = self._get_world_boss_summon_material_cost()
            if summon_cost > 0:
                lines.append(self._overlay_kv("召喚", f"!wb 召喚 / 強化素材合計 {summon_cost}"))
            last_result = status.get("last_result", {})
            if isinstance(last_result, dict) and last_result:
                result_boss_name = str(last_result.get("boss_name", "") or "").strip() or "WB"
                result_state = "討伐済み" if bool(last_result.get("cleared", False)) else "時間切れ"
                lines.append(self._overlay_kv("前回", f"{result_boss_name} / {result_state}"))
                ranking_summary = self._build_world_boss_ranking_summary(
                    [entry for entry in last_result.get("ranking", []) if isinstance(entry, dict)]
                )
                if ranking_summary != "なし":
                    lines.append(self._overlay_kv("前回順位", ranking_summary))
            return [line for line in lines if line]

        if phase == "cooldown":
            remain = max(0, int(float(status.get("cooldown_ends_at", 0.0)) - now_ts()))
            lines.append(self._overlay_kv("状態", f"クールダウン / 残り {self.bot.rpg.format_duration(remain)}"))
            last_result = status.get("last_result", {})
            if isinstance(last_result, dict) and last_result:
                result_state = "討伐済み" if bool(last_result.get("cleared", False)) else "時間切れ"
                lines.append(self._overlay_kv("前回", f"{boss_name} / {result_state}"))
            return [line for line in lines if line]

        lines.append(self._overlay_kv("WB", boss_name if not boss_title else f"{boss_name} / {boss_title}"))
        lines.append(self._overlay_kv("参加人数", f"{int(status.get('participants', 0))}人"))

        if phase == "recruiting":
            remain = max(0, int(float(status.get("join_ends_at", 0.0)) - now_ts()))
            lines.append(self._overlay_kv("状態", f"募集中 / 残り {self.bot.rpg.format_duration(remain)}"))
        elif phase == "active":
            current_hp = max(0, int(status.get("current_hp", 0)))
            max_hp = max(1, int(status.get("max_hp", 1)))
            remain = max(0, int(float(status.get("ends_at", 0.0)) - now_ts()))
            hp_pct = int(round((current_hp / max_hp) * 100))
            lines.append(self._overlay_kv("状態", f"戦闘中 / 残り {self.bot.rpg.format_duration(remain)}"))
            lines.append(self._overlay_kv("HP", f"{current_hp}/{max_hp} ({hp_pct}%)"))

        if phase_label:
            lines.append(self._overlay_kv("フェーズ", phase_label))
        if event_text:
            lines.append(self._overlay_kv("イベント", event_text))
        if leader_name and race_focus_active:
            race_text = f"#1 {leader_name} {leader_score}"
            if runner_up_name:
                race_text += f" / #2 {runner_up_name} {runner_up_score} / 差 {leader_gap}"
            lines.append(self._overlay_kv("総合貢献王争い", race_text))
        if ranking:
            lines.append(self._overlay_kv("順位", self._build_world_boss_ranking_summary(ranking)))

        self_status = status.get("self")
        if isinstance(self_status, dict):
            self_hp = max(0, int(self_status.get("current_hp", 0)))
            self_max_hp = max(1, int(self_status.get("snapshot_max_hp", 1)))
            self_rank = max(0, int(self_status.get("rank", 0)))
            self_rank_text = f"#{self_rank}" if self_rank > 0 else "圏外"
            self_alive = "生存" if bool(self_status.get("alive", False)) else "離脱中"
            lines.append(
                self._overlay_kv(
                    "自分",
                    (
                        f"{self_rank_text} / {self_alive} / "
                        f"HP {self_hp}/{self_max_hp} / "
                        f"{int(self_status.get('total_damage', 0))}ダメ / "
                        f"貢献 {int(self_status.get('total_contribution_score', self_status.get('contribution_score', 0)))}"
                    ),
                )
            )

        if recent_logs:
            lines.append(self._overlay_section("直近ログ"))
            for index, log_line in enumerate(recent_logs[-5:], start=1):
                lines.append(self._overlay_kv(str(index), log_line))

        return [line for line in lines if line]

    def _build_world_boss_status_reply(self, display_name: str, status: Dict[str, Any]) -> str:
        phase = str(status.get("phase", "idle") or "idle").strip()
        boss = status.get("boss", {})
        boss_name = str(boss.get("name", "WB") or "WB").strip() or "WB"
        if phase == "idle":
            summon_cost = self._get_world_boss_summon_material_cost()
            if summon_cost > 0:
                return self._build_detail_hint_reply(
                    display_name,
                    "WB待機中",
                    f"!wb 召喚",
                    f"強化素材合計 {summon_cost}",
                )
            return self._build_detail_hint_reply(display_name, "WB待機中")
        if phase == "cooldown":
            remain = max(0, int(float(status.get("cooldown_ends_at", 0.0)) - now_ts()))
            return self._build_detail_hint_reply(
                display_name,
                "WBクールダウン",
                f"残り {self.bot.rpg.format_duration(remain)}",
            )
        if phase == "recruiting":
            remain = max(0, int(float(status.get("join_ends_at", 0.0)) - now_ts()))
            return self._build_detail_hint_reply(
                display_name,
                "WB募集",
                boss_name,
                f"残り {self.bot.rpg.format_duration(remain)}",
                f"{int(status.get('participants', 0))}人",
            )
        current_hp = max(0, int(status.get("current_hp", 0)))
        max_hp = max(1, int(status.get("max_hp", 1)))
        remain = max(0, int(float(status.get("ends_at", 0.0)) - now_ts()))
        return self._build_detail_hint_reply(
            display_name,
            boss_name,
            f"HP {current_hp}/{max_hp}",
            f"残り {self.bot.rpg.format_duration(remain)}",
        )

    def _build_world_boss_shop_lines(self, display_name: str, user: Dict[str, Any]) -> List[str]:
        shop = self.bot.rpg.get_world_boss_shop_catalog(user)
        recipes = [recipe for recipe in shop.get("recipes", []) if isinstance(recipe, dict)]
        skill_book_targets = [
            target
            for target in shop.get("skill_book_targets", [])
            if isinstance(target, dict)
        ]
        example_skill_name = "闘気"
        if skill_book_targets:
            example_skill_name = (
                str(skill_book_targets[0].get("skill_name", example_skill_name) or example_skill_name).strip()
                or example_skill_name
            )
        lines = [
            self._overlay_section("WBショップ"),
            self._overlay_kv("コマンド", "!wb ショップ"),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("スキル書", self._format_skill_book_holdings_summary(shop)),
            self._overlay_kv("WB素材", self._format_world_boss_base_materials_summary(user)),
        ]
        if not recipes:
            lines.append(self._overlay_kv("交換", "設定なし"))
            return [line for line in lines if line]

        if skill_book_targets:
            target_labels = [
                str(target.get("skill_book_label", "スキルの書") or "スキルの書").strip() or "スキルの書"
                for target in skill_book_targets[:4]
            ]
            if target_labels:
                lines.append(self._overlay_kv("交換先", " / ".join(target_labels)))

        lines.append(self._overlay_section("交換一覧"))
        for index, recipe in enumerate(recipes, start=1):
            lines.append(
                self._overlay_kv(
                    str(index),
                    (
                        f"{recipe.get('material_label', '?')} {int(recipe.get('current_amount', 0))}/"
                        f"{int(recipe.get('cost', 0))} -> 指定スキルの書x1 "
                        f"(交換可能 {int(recipe.get('purchasable', 0))})"
                    ),
                )
            )
        lines.append(f"実行: !wb 交換 {example_skill_name} [冊数]")
        return [line for line in lines if line]

    def _build_world_boss_shop_reply(self, display_name: str, user: Dict[str, Any]) -> str:
        shop = self.bot.rpg.get_world_boss_shop_catalog(user)
        recipes = [recipe for recipe in shop.get("recipes", []) if isinstance(recipe, dict)]
        skill_book_targets = [
            target
            for target in shop.get("skill_book_targets", [])
            if isinstance(target, dict)
        ]
        available_total = sum(max(0, int(recipe.get("purchasable", 0) or 0)) for recipe in recipes)
        example_skill_name = "闘気"
        if skill_book_targets:
            example_skill_name = (
                str(skill_book_targets[0].get("skill_name", example_skill_name) or example_skill_name).strip()
                or example_skill_name
            )
        return self._build_detail_hint_reply(
            display_name,
            "WBショップ",
            f"交換可能 {available_total}冊",
            f"例 !wb 交換 {example_skill_name} / !wb 交換 {example_skill_name} 2",
        )

    def _build_world_boss_result_lines(self, display_name: str, result: Dict[str, Any]) -> List[str]:
        rewards = result.get("rewards", {})
        material_label = str(rewards.get("material_label", "") or "").strip()
        material_amount = max(0, int(rewards.get("material_amount", 0)))
        titled_display_name = self._format_titled_display_name(
            display_name,
            str(result.get("title_label", "") or "").strip(),
        )
        reward_parts = [
            f"+{max(0, int(rewards.get('exp', 0)))}EXP",
            f"+{max(0, int(rewards.get('gold', 0)))}G",
        ]
        if material_label and material_amount > 0:
            reward_parts.append(f"{material_label}x{material_amount}")
        elif material_label:
            reward_parts.append(f"{material_label}x0")

        lines = [
            self._overlay_section("WB結果"),
            self._overlay_kv("コマンド", "!wb 結果"),
            self._overlay_kv("ユーザー", titled_display_name),
            self._overlay_kv(
                "結果",
                (
                    f"{str(result.get('boss_name', 'WB') or 'WB').strip()} / "
                    f"{'討伐成功' if bool(result.get('cleared', False)) else '時間切れ'}"
                ),
            ),
            self._overlay_kv(
                "戦果",
                (
                    f"順位 #{max(1, int(result.get('rank', 1)))} / "
                    f"{max(0, int(result.get('total_damage', 0)))}ダメ / "
                    f"貢献 {max(0, int(result.get('total_contribution_score', result.get('contribution_score', 0))))} / "
                    f"離脱 {max(0, int(result.get('times_downed', 0)))}回"
                ),
            ),
            self._overlay_kv("貢献内訳", self._format_world_boss_contribution_breakdown(result)),
            self._overlay_kv("報酬", " / ".join(reward_parts)),
        ]
        new_achievements = [
            str(summary).strip()
            for summary in result.get("new_achievements", [])
            if str(summary).strip()
        ]
        if new_achievements:
            lines.append(self._overlay_kv("新実績", " / ".join(new_achievements)))
        new_titles = [
            str(summary).strip()
            for summary in result.get("new_titles", [])
            if str(summary).strip()
        ]
        if new_titles:
            lines.append(self._overlay_kv("新称号", " / ".join(new_titles), alert=True))
        if not bool(result.get("eligible", False)):
            lines.append(self._overlay_kv("補足", "参加条件未達のため報酬なし"))
        return [line for line in lines if line]

    def _build_world_boss_result_reply(self, display_name: str, result: Dict[str, Any]) -> str:
        rewards = result.get("rewards", {})
        reward_parts = [
            f"+{max(0, int(rewards.get('exp', 0)))}EXP",
            f"+{max(0, int(rewards.get('gold', 0)))}G",
        ]
        material_label = str(rewards.get("material_label", "") or "").strip()
        material_amount = max(0, int(rewards.get("material_amount", 0)))
        if material_label and material_amount > 0:
            reward_parts.append(f"{material_label}x{material_amount}")
        new_titles = [
            str(summary).strip()
            for summary in result.get("new_titles", [])
            if str(summary).strip()
        ]
        return self._build_detail_hint_reply(
            display_name,
            str(result.get("boss_name", "WB") or "WB").strip() or "WB",
            f"#{max(1, int(result.get('rank', 1)))}",
            *reward_parts,
            f"新称号 {new_titles[0]}" if new_titles else "",
        )

    def _build_world_boss_ranking_lines(self, display_name: str, status: Dict[str, Any]) -> List[str]:
        phase = str(status.get("phase", "idle") or "idle").strip()
        ranking = [
            entry for entry in status.get("ranking", []) if isinstance(entry, dict)
        ]
        if not ranking:
            last_result = status.get("last_result", {})
            if isinstance(last_result, dict):
                ranking = [
                    entry for entry in last_result.get("ranking", []) if isinstance(entry, dict)
                ]

        lines = [
            self._overlay_section("WBランキング"),
            self._overlay_kv("コマンド", "!wb ランキング"),
            self._overlay_kv("ユーザー", display_name),
            self._overlay_kv("状態", phase or "idle"),
        ]
        if not ranking:
            lines.append(self._overlay_kv("順位", "データなし"))
            return lines

        for entry in ranking[:5]:
            entry_name = self._format_titled_display_name(
                str(entry.get("display_name", "?") or "?").strip() or "?",
                str(entry.get("title_label", "") or "").strip(),
            )
            lines.append(
                self._overlay_kv(
                    f"#{max(1, int(entry.get('rank', 1)))}",
                    (
                        f"{entry_name} / "
                        f"{max(0, int(entry.get('total_damage', 0)))}ダメ / "
                        f"貢献 {max(0, int(entry.get('total_contribution_score', entry.get('contribution_score', 0))))}"
                    ),
                )
            )
        return lines

    def _build_world_boss_ranking_reply(self, display_name: str, status: Dict[str, Any]) -> str:
        ranking = [
            entry for entry in status.get("ranking", []) if isinstance(entry, dict)
        ]
        if not ranking:
            last_result = status.get("last_result", {})
            if isinstance(last_result, dict):
                ranking = [
                    entry for entry in last_result.get("ranking", []) if isinstance(entry, dict)
                ]
        if not ranking:
            return self._build_detail_hint_reply(display_name, "WBランキング", "データなし")
        top_entry = ranking[0]
        return self._build_detail_hint_reply(
            display_name,
            "WBランキング",
            (
                "1位 "
                + self._format_titled_display_name(
                    str(top_entry.get("display_name", "?") or "?").strip() or "?",
                    str(top_entry.get("title_label", "") or "").strip(),
                )
            ),
            f"{max(0, int(top_entry.get('total_damage', 0)))}ダメ",
        )

    def _parse_detail_page(self, page_text: Optional[str]) -> int:
        text = nfkc(page_text or "").strip()
        if not text:
            return 1

        try:
            return max(1, int(text))
        except (TypeError, ValueError):
            return 1

    def _truncate_chat_text(self, text: str, *, limit: int = 430) -> str:
        normalized = " ".join(str(text).split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(1, limit - 1)].rstrip() + "…"

    def _get_available_exploration_detail(
        self,
        user: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        explore = user.get("explore", {})
        if explore.get("state") == "exploring":
            remain = int(explore.get("ends_at", 0) - now_ts())
            if remain > 0 or bool(explore.get("auto_repeat", False)):
                return None, "exploring", None

            result = explore.get("result")
            if isinstance(result, dict):
                return result, "pending_claim", "受取前"

        last_result = user.get("last_exploration_result")
        if isinstance(last_result, dict):
            return last_result, "claimed", "受取済み"

        return None, None, None

    def _format_drop_items_summary(self, drop_items: List[Dict[str, Any]]) -> str:
        if not drop_items:
            return ""

        preview = " / ".join(
            self.bot.rpg.format_item_brief(item)
            for item in drop_items[:2]
        )
        if len(drop_items) > 2:
            preview += f" / ...他{len(drop_items) - 2}件"
        return preview

    def _format_material_reward_summary(self, result: Dict[str, Any]) -> str:
        material_line = self._build_material_line(
            result.get("drop_materials", {}),
            result.get("drop_enchant_materials", {}),
        )
        return material_line

    def _build_exploration_detail_summary_message(
        self,
        display_name: str,
        result: Dict[str, Any],
        *,
        detail_state_label: str,
        total_pages: int,
        page_label: str = "探索結果詳細",
        truncate: bool = True,
    ) -> str:
        area_name = result.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode = self.bot.rpg.resolve_exploration_mode(result.get("mode"))
        exp_gain = int(result.get("exp", 0))
        gold_gain = int(result.get("gold", 0))
        battle_count = get_battle_count(result)
        total_turns = int(result.get("total_turns", 0))
        exploration_runs = max(1, int(result.get("exploration_runs", 1)))
        hp_after = int(result.get("hp_after", 0))
        downed = bool(result.get("downed", False) or not bool(result.get("returned_safe", True)))
        return_reason = result.get("return_reason", "探索終了")
        segments = [
            f"{mode['label']} {area_name}",
            "戦闘不能" if downed else "帰還",
            f"帰還理由:{return_reason}",
            f"+{exp_gain}EXP +{gold_gain}G",
            f"{battle_count}戦 {total_turns}T",
            f"探索終了HP:{hp_after}",
            f"致死耐性:{self._format_guard_usage(result.get('armor_guards_used', 0), result.get('armor_guards_total', 0))}",
        ]
        if exploration_runs > 1:
            segments.insert(0, f"{exploration_runs}回分")
        drop_summary = self._format_drop_items_summary(result.get("drop_items", []))
        if drop_summary:
            segments.append(drop_summary)
        material_summary = self._format_material_reward_summary(result)
        if material_summary:
            segments.append(material_summary)
        text = " | ".join(segments)
        if not truncate:
            return text
        return self._truncate_chat_text(text)

    def _build_exploration_battle_detail_message(
        self,
        display_name: str,
        battle: Dict[str, Any],
        *,
        page: int,
        total_pages: int,
        detail_state_label: str,
        page_label: str = "探索結果詳細",
        truncate: bool = True,
    ) -> str:
        battle_text = self._format_battle_log_block(page - 1, battle).replace("\n", " | ")
        text = f"{page_label} {page}/{total_pages} | {battle_text}"
        if not truncate:
            return text
        return self._truncate_chat_text(text)

    def _build_exploration_detail_message(
        self,
        display_name: str,
        user: Dict[str, Any],
        *,
        page: int,
    ) -> str:
        result, detail_state, detail_state_label = self._get_available_exploration_detail(user)
        if detail_state == "exploring":
            explore = user.get("explore", {})
            area_name = explore.get("area", DEFAULT_AREA)
            if area_name not in AREAS:
                area_name = DEFAULT_AREA
            mode = self.bot.rpg.resolve_exploration_mode(explore.get("mode"))
            remain = max(0, int(explore.get("ends_at", 0) - now_ts()))
            if bool(explore.get("auto_repeat", False)):
                return (
                    f"{display_name} は {mode['label']} {area_name} を探索継続中です。"
                    "詳細は停止後に !探索 結果"
                )
            return (
                f"{display_name} は {mode['label']} {area_name} を探索中です。"
                f"残り {self.bot.rpg.format_duration(remain)} / 詳細は完了後に !探索 結果"
            )

        if not isinstance(result, dict) or not detail_state_label:
            return f"{display_name} は表示できる探索結果がありません。"

        actual_battle_logs = self._get_actual_battle_logs(result)
        total_pages = max(1, len(actual_battle_logs) + 1)
        safe_page = min(max(1, page), total_pages)

        if safe_page == 1:
            return self._build_exploration_detail_summary_message(
                display_name,
                result,
                detail_state_label=detail_state_label,
                total_pages=total_pages,
            )

        return self._build_exploration_battle_detail_message(
            display_name,
            actual_battle_logs[safe_page - 2],
            page=safe_page,
            total_pages=total_pages,
            detail_state_label=detail_state_label,
        )

    def _build_exploration_result_reply_message(
        self,
        display_name: str,
        result: Dict[str, Any],
        *,
        claimed_now: bool,
        current_level: int,
        current_gold: int,
    ) -> str:
        area_name = result.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode = self.bot.rpg.resolve_exploration_mode(result.get("mode"))
        battle_count = get_battle_count(result)
        exploration_runs = max(1, int(result.get("exploration_runs", 1)))
        downed = bool(result.get("downed", False) or not bool(result.get("returned_safe", True)))
        auto_potions_bought = int(result.get("auto_potions_bought", 0))
        new_titles = [
            str(summary).strip()
            for summary in result.get("new_titles", [])
            if str(summary).strip()
        ]
        new_achievements = [
            str(summary).strip()
            for summary in result.get("new_achievements", [])
            if str(summary).strip()
        ]
        area_depth_record_update = result.get("area_depth_record_update")
        area_depth_record_note = ""
        if isinstance(area_depth_record_update, dict):
            if bool(area_depth_record_update.get("holder_changed", False)):
                area_depth_record_note = "最深記録交代"
            elif bool(area_depth_record_update.get("is_first_record", False)):
                area_depth_record_note = "最深記録登録"
            else:
                area_depth_record_note = "最深記録更新"

        label = "探索受取" if claimed_now else "最新探索"
        run_note = f"{exploration_runs}回分" if exploration_runs > 1 else ""
        battle_note = f"{battle_count}戦" if battle_count > 0 else ""
        return self._build_detail_hint_reply(
            display_name,
            label,
            run_note,
            f"{mode['label']} {area_name}",
            "戦闘不能" if downed else "帰還",
            battle_note,
            f"P補充+{auto_potions_bought}" if auto_potions_bought > 0 else "",
            area_depth_record_note,
            f"新称号 {new_titles[0]}" if new_titles else "",
            f"新実績 {new_achievements[0]}" if (not new_titles and new_achievements) else "",
        )

    async def _handle_exploration_result_command(
        self,
        ctx: commands.Context,
    ) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        result, detail_state, detail_state_label = self._get_available_exploration_detail(user)

        if detail_state == "exploring":
            explore = user.get("explore", {})
            remain = max(0, int(explore.get("ends_at", 0) - now_ts()))
            if bool(explore.get("auto_repeat", False)):
                await ctx.reply(f"{display_name} の探索は継続中です。停止後に `!探索 結果`")
            else:
                await ctx.reply(
                    f"{display_name} の探索はまだ途中です。残り {self.bot.rpg.format_duration(remain)}"
                )
            return

        if not isinstance(result, dict) or not detail_state_label:
            await ctx.reply(f"{display_name} は表示できる探索結果がありません。")
            return

        claimed_now = False
        if detail_state == "pending_claim":
            explore = user.get("explore", {})
            self.bot.rpg.finalize_exploration(username)
            self.bot.save_data()
            self.bot.enqueue_exploration_result_tts(display_name, result)
            user = self.bot.rpg.get_user(username)
            latest_result = user.get("last_exploration_result")
            if isinstance(latest_result, dict):
                result = latest_result
            detail_state_label = "受取完了"
            claimed_now = True

        self._show_detail_overlay(
            f"{display_name} / !探索 結果",
            self._build_exploration_result_lines(
                display_name,
                result,
                command_name="!探索 結果",
                detail_state_label=detail_state_label,
            ),
        )
        await ctx.reply(
            self._build_exploration_result_reply_message(
                display_name,
                result,
                claimed_now=claimed_now,
                current_level=self.bot.rpg.get_adventure_level(user),
                current_gold=int(user.get("gold", 0)),
            )
        )

    def _build_battle_detail_lines(
        self,
        display_name: str,
        result: Dict[str, Any],
        *,
        detail_state_label: str,
        battle_number: Optional[int],
    ) -> Tuple[List[str], Optional[int], int]:
        area_name = result.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode = self.bot.rpg.resolve_exploration_mode(result.get("mode"))
        actual_battles = self._get_actual_battle_logs(result)
        total_battles = len(actual_battles)
        exploration_runs = max(1, int(result.get("exploration_runs", 1)))
        lines = [
            "コマンド: !探索 戦闘",
            f"ユーザー: {display_name}",
            f"探索: {mode['label']} / {area_name}",
        ]
        if exploration_runs > 1:
            lines.append(f"集計: {exploration_runs}回分")

        if total_battles <= 0:
            lines.append("戦闘詳細: 表示できる戦闘ログがありません")
            lines.append(format_return_footer(result))
            return lines, None, 0

        if battle_number is None:
            lines.append(f"表示範囲: 全戦闘 / {total_battles}戦")
            for index, battle in enumerate(actual_battles, start=1):
                lines.append(self._build_single_battle_detail_block(index, battle))
            lines.append(format_return_footer(result))
            return lines, None, total_battles

        safe_battle_number = min(max(1, int(battle_number)), total_battles)
        lines.append(f"表示範囲: 第{safe_battle_number}戦 / 全{total_battles}戦")
        lines.append(
            self._build_single_battle_detail_block(
                safe_battle_number,
                actual_battles[safe_battle_number - 1],
            )
        )
        lines.append(format_return_footer(result))
        return lines, safe_battle_number, total_battles

    def _build_battle_detail_reply_message(
        self,
        display_name: str,
        *,
        selected_battle_number: Optional[int],
        total_battles: int,
    ) -> str:
        if total_battles <= 0:
            return f"{display_name} は表示できる戦闘詳細がありません。"

        scope = (
            f"第{selected_battle_number}戦 / 全{total_battles}戦"
            if selected_battle_number is not None
            else f"全{total_battles}戦"
        )
        return self._build_detail_hint_reply(display_name, "探索戦闘", scope)

    async def _handle_battle_detail_command(
        self,
        ctx: commands.Context,
        *,
        page_text: Optional[str],
    ) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        result, detail_state, detail_state_label = self._get_available_exploration_detail(user)

        if detail_state == "exploring":
            explore = user.get("explore", {})
            remain = max(0, int(explore.get("ends_at", 0) - now_ts()))
            if bool(explore.get("auto_repeat", False)):
                await ctx.reply(f"{display_name} の探索は継続中です。停止後に `!探索 戦闘`")
            else:
                await ctx.reply(
                    f"{display_name} の探索はまだ途中です。残り {self.bot.rpg.format_duration(remain)}"
                )
            return

        if not isinstance(result, dict) or not detail_state_label:
            await ctx.reply(f"{display_name} は表示できる戦闘詳細がありません。")
            return

        battle_number = None if not (page_text or "").strip() else self._parse_detail_page(page_text)
        lines, selected_battle_number, total_battles = self._build_battle_detail_lines(
            display_name,
            result,
            detail_state_label=detail_state_label,
            battle_number=battle_number,
        )
        self._show_detail_overlay(f"{display_name} / !探索 戦闘", lines)
        await ctx.reply(
            self._build_battle_detail_reply_message(
                display_name,
                selected_battle_number=selected_battle_number,
                total_battles=total_battles,
            )
        )

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        await ctx.reply("pong")

    @commands.command(name="discord", aliases=("ディスコード", "参加URL", "招待", "invite"))
    async def discord_invite(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, _ = self._split_subcommand(args)
        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)

        if subcommand in {"help", "使い方"}:
            await ctx.reply(
                self._show_help_topic(
                    display_name,
                    "!discord",
                    self._build_discord_help_lines(),
                    "Discord案内",
                )
            )
            return

        if subcommand:
            await ctx.reply(f"{display_name} `!discord` を使ってください。")
            return

        invite_url = self._get_discord_invite_url()
        if invite_url:
            await ctx.reply(f"{display_name} Discord参加URL: {invite_url}")
            return

        await ctx.reply(
            f"{display_name} Discord参加URL はまだ公開されていません。"
            " 配信概要欄か `!ヘルプ` を確認してください。"
        )

    @commands.command(name="exp")
    async def exp(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        chat_exp = int(user.get("chat_exp", 0))
        adventure_exp = int(user.get("adventure_exp", 0))
        level_exp = self.bot.rpg.get_level_exp(user)
        level = self.bot.rpg.get_adventure_level(user)
        await ctx.reply(
            f"{display_name} chat_exp:{chat_exp} / 冒険EXP:{adventure_exp} / "
            f"Lv反映EXP:{level_exp} / Lv{level}"
        )

    @commands.command(name="状態", aliases=("me", "status"))
    async def me(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if subcommand in {"hp", "体力"}:
            await self.hp.callback(self, ctx)
            return
        if subcommand in {"exp"}:
            await self.exp.callback(self, ctx)
            return
        if subcommand in {"ポーション", "potion", "buy", "回復"}:
            qty = None
            if remainder:
                qty, extra = self._parse_int_argument(remainder)
                if qty is None or extra:
                    username, display_name = self._get_identity(ctx)
                    await ctx.reply(
                        f"{display_name} `!状態 ポーション` または "
                        f"`!状態 ポーション 0-{MAX_POTIONS_PER_EXPLORATION}` を使ってください。"
                    )
                    return
            await self.buy_potion.callback(self, ctx, qty=qty)
            return
        if subcommand in {"蘇生", "revive"}:
            await self.revive.callback(self, ctx)
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !状態",
                self._build_status_help_lines(),
            )
            await ctx.reply(self._build_detail_hint_reply(display_name, "状態ヘルプ"))
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!状態` `!状態 HP` `!状態 EXP` "
                f"`!状態 ポーション 5` `!状態 ポーション 0` を使ってください。"
            )
            return

        username, display_name = self._get_identity(ctx)

        user = self.bot.rpg.get_user(username)
        level = self.bot.rpg.get_adventure_level(user)
        hp = int(user.get("hp", DEFAULT_MAX_HP))
        max_hp = int(user.get("max_hp", DEFAULT_MAX_HP))
        explore = user.get("explore", {})
        title_note = self._get_active_title_label(user)
        self._show_detail_overlay(
            f"{display_name} / !状態",
            self._build_me_detail_lines(display_name, user),
        )

        if user.get("down", False):
            await ctx.reply(
                self._build_detail_hint_reply(
                    display_name,
                    title_note,
                    f"Lv{level}",
                    f"HP:{hp}/{max_hp}",
                    "戦闘不能",
                )
            )
            return

        if explore.get("state") == "exploring":
            remain = max(0, int(explore.get("ends_at", 0) - now_ts()))
            mode = self.bot.rpg.resolve_exploration_mode(explore.get("mode"))
            area_name = explore.get("area", DEFAULT_AREA)
            auto_repeat_active = bool(explore.get("auto_repeat", False))
            if area_name not in AREAS:
                area_name = DEFAULT_AREA
            if auto_repeat_active:
                await ctx.reply(
                    self._build_detail_hint_reply(
                        display_name,
                        title_note,
                        f"Lv{level}",
                        f"HP:{hp}/{max_hp}",
                        f"{mode['label']} {area_name}",
                        (
                            f"残り {self.bot.rpg.format_duration(remain)}"
                            if remain > 0
                            else "継続中"
                        ),
                    )
                )
                return
            if remain <= 0:
                await ctx.reply(
                    self._build_detail_hint_reply(
                        display_name,
                        title_note,
                        "探索完了",
                        "`!探索 結果`",
                    )
                )
                return
            await ctx.reply(
                self._build_detail_hint_reply(
                    display_name,
                    title_note,
                    f"Lv{level}",
                    f"HP:{hp}/{max_hp}",
                    f"{mode['label']} {area_name}",
                    f"残り {self.bot.rpg.format_duration(remain)}",
                )
            )
            return

        await ctx.reply(
            self._build_detail_hint_reply(
                display_name,
                title_note,
                f"Lv{level}",
                f"HP:{hp}/{max_hp}",
                "待機中",
            )
        )

    @commands.command(name="hp", aliases=("体力",))
    async def hp(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)

        hp = int(user.get("hp", DEFAULT_MAX_HP))
        max_hp = int(user.get("max_hp", DEFAULT_MAX_HP))
        potions = int(user.get("potions", 0))
        explore = user.get("explore", {})
        active_mode = self.bot.rpg.resolve_exploration_mode(
            explore.get("mode") if explore.get("state") == "exploring" else None
        )
        atk, defense = self.bot.rpg.get_player_combat_stats(user, active_mode["key"])
        speed = getattr(self.bot.rpg, "get_player_speed", lambda _user: 0)(user)
        weapon_bonus = self._format_weapon_bonus(user)
        ring_bonus = self._format_ring_bonus(user)
        weapon_enchant = self._format_slot_enchant_status(user, "weapon")
        armor_enchant = self._format_slot_enchant_status(user, "armor")
        ring_enchant = self._format_slot_enchant_status(user, "ring")
        shoes_enchant = self._format_slot_enchant_status(user, "shoes")
        state = "戦闘不能" if user.get("down", False) else "行動可能"

        await ctx.reply(
            f"{display_name} HP:{hp}/{max_hp} / A:{atk} / D:{defense} / S:{speed} / "
            f"ポーション:{potions} / 致死耐性:{self._format_guard_count_for_user(user)} / "
            f"武器E:{weapon_enchant} / 防具E:{armor_enchant} / 装飾E:{ring_enchant} / 靴E:{shoes_enchant} / "
            f"武器:{weapon_bonus} / 装飾:{ring_bonus} / "
            f"スキル:{self._format_skill_loadout_summary(user)} / "
            f"状態:{state}"
        )

    @commands.command(name="スキル", aliases=("skills", "skill"))
    async def skills(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if subcommand in {"強化", "skillup", "skillupgrade", "upgrade"}:
            await self.upgrade_skill.callback(self, ctx, skill_name=remainder or None)
            return
        if subcommand in {"変更", "切替", "skillset", "setskill", "set"}:
            await self.set_active_skill.callback(self, ctx, skill_name=remainder or None)
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !スキル",
                self._build_skill_help_lines(),
            )
            await ctx.reply(self._build_detail_hint_reply(display_name, "スキルヘルプ"))
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!スキル` `!スキル 強化 <名前>` `!スキル 変更 <名前>` を使ってください。"
            )
            return

        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !スキル",
            self._build_skill_detail_lines(display_name, user),
        )
        await ctx.reply(self._build_skill_reply(display_name, user))

    @commands.command(name="スキル強化", aliases=("skillup", "skillupgrade", "スキルUP"))
    async def upgrade_skill(self, ctx: commands.Context, *, skill_name: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.upgrade_skill(username, skill_name)
        if ok:
            self.bot.save_data()
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !スキル",
            self._build_skill_detail_lines(display_name, user),
        )
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="スキル変更", aliases=("skillset", "setskill", "スキル切替"))
    async def set_active_skill(self, ctx: commands.Context, *, skill_name: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        if not str(skill_name or "").strip():
            user = self.bot.rpg.get_user(username)
            current_name = str(
                self._format_skill_label(self.bot.rpg.get_selected_active_skill(user))
            ).strip() or "なし"
            await ctx.reply(
                f"{display_name} 切替先を指定してください。 "
                f"現在 {current_name} / `!スキル 変更 <スキル名>` / "
                f"`!スキル変更 パッシブ 1 闘魂 2 鉄壁 3 迅雷`"
            )
            return

        skill_type, remainder = self._split_subcommand(skill_name)
        if skill_type in {"パッシブ", "passive", "p"}:
            if self._looks_like_indexed_skill_loadout(remainder):
                slot_queries, error = self._parse_indexed_skill_loadout(remainder)
                ok, msg = (False, error or "パッシブ構成を解釈できませんでした。")
                if not error:
                    ok, msg = self.bot.rpg.set_selected_skill_loadout(username, "passive", slot_queries)
            else:
                ok, msg = self.bot.rpg.set_selected_passive_skill(username, remainder or None)
        elif skill_type in {"アクティブ", "active", "a"}:
            if self._looks_like_indexed_skill_loadout(remainder):
                slot_queries, error = self._parse_indexed_skill_loadout(remainder)
                ok, msg = (False, error or "アクティブ構成を解釈できませんでした。")
                if not error:
                    ok, msg = self.bot.rpg.set_selected_skill_loadout(username, "active", slot_queries)
            else:
                ok, msg = self.bot.rpg.set_selected_active_skill(username, remainder or None)
        else:
            ok, msg = self.bot.rpg.set_selected_active_skill(username, skill_name)
        if ok:
            self.bot.save_data()
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !スキル",
            self._build_skill_detail_lines(display_name, user),
        )
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="称号", aliases=("title", "titles"))
    async def titles(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if subcommand in {"変更", "set", "change"}:
            username, display_name = self._get_identity(ctx)
            ok, msg = self.bot.rpg.set_active_title(username, remainder or None)
            if ok:
                self.bot.save_data()
            user = self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !称号",
                self._build_title_detail_lines(display_name, user),
            )
            await ctx.reply(f"{display_name} {msg}")
            return
        if subcommand in {"解除", "off", "clear"}:
            username, display_name = self._get_identity(ctx)
            ok, msg = self.bot.rpg.set_active_title(username, "解除")
            if ok:
                self.bot.save_data()
            user = self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !称号",
                self._build_title_detail_lines(display_name, user),
            )
            await ctx.reply(f"{display_name} {msg}")
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            await ctx.reply(
                self._show_help_topic(
                    display_name,
                    "!称号",
                    self._build_title_help_lines(),
                    "称号ヘルプ",
                )
            )
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            ok, msg = self.bot.rpg.set_active_title(username, args)
            if ok:
                self.bot.save_data()
            user = self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !称号",
                self._build_title_detail_lines(display_name, user),
            )
            await ctx.reply(f"{display_name} {msg}")
            return

        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !称号",
            self._build_title_detail_lines(display_name, user),
        )
        await ctx.reply(self._build_title_reply(display_name, user))

    @commands.command(name="wb", aliases=("worldboss", "ワールドボス"))
    async def world_boss_status(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if subcommand.isdigit() and not remainder:
            await self.world_boss_start.callback(self, ctx, boss_id=subcommand)
            return
        if await self._dispatch_subcommand(
            ctx,
            subcommand,
            remainder,
            [
                ({"ショップ", "shop", "wbshop"}, self.world_boss_shop.callback, None),
                ({"交換", "exchange", "wbexchange"}, self.world_boss_exchange.callback, "item_name"),
                ({"召喚", "summon", "wbsummon"}, self.world_boss_summon.callback, None),
                ({"参加", "join", "wbjoin"}, self.world_boss_join.callback, None),
                ({"離脱", "leave", "wbleave"}, self.world_boss_leave.callback, None),
                ({"結果", "result", "wbresult"}, self.world_boss_result.callback, None),
                ({"ランキング", "rank", "wbrank"}, self.world_boss_ranking.callback, None),
                ({"開始", "start", "wbstart"}, self.world_boss_start.callback, "boss_id"),
                ({"終了", "stop", "wbstop"}, self.world_boss_stop.callback, None),
                ({"スキップ", "skip", "wbskip"}, self.world_boss_skip.callback, None),
            ],
        ):
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            await ctx.reply(
                self._show_help_topic(
                    display_name,
                    "!wb",
                    self._build_world_boss_help_lines(),
                    "WBヘルプ",
                )
            )
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            owner_hint = ""
            if self._is_owner(ctx):
                selector_options = self._format_world_boss_selector_options()
                if selector_options:
                    owner_hint = f" 配信者デバッグ用に !wb <番号> / !wb終了 も使えます。 {selector_options}"
            await ctx.reply(
                f"{display_name} `!wb 召喚` `!wb 参加` `!wb 結果` `!wb ショップ` `!wb 交換 <名前> [冊数]` を使ってください。{owner_hint}"
            )
            return

        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        status = self.bot.rpg.get_world_boss_status(username)
        self._show_detail_overlay(
            f"{display_name} / !wb",
            self._build_world_boss_status_lines(display_name, status),
        )
        await ctx.reply(self._build_world_boss_status_reply(display_name, status))

    @commands.command(name="wbショップ", aliases=("wbshop", "worldbossshop", "ワールドボスショップ"))
    async def world_boss_shop(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !wb ショップ",
            self._build_world_boss_shop_lines(display_name, user),
        )
        await ctx.reply(self._build_world_boss_shop_reply(display_name, user))

    @commands.command(name="wb交換", aliases=("wbexchange", "worldbossexchange", "ワールドボス交換"))
    async def world_boss_exchange(self, ctx: commands.Context, *, item_name: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        skill_name, quantity = self._parse_trailing_int_argument(item_name)
        if not skill_name:
            user = self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !wb ショップ",
                self._build_world_boss_shop_lines(display_name, user),
            )
            await ctx.reply(f"{display_name} 交換先のスキル名を指定してください。 `!wb 交換 闘気` / `!wb 交換 闘気 2`")
            return
        if quantity is not None and quantity <= 0:
            user = self.bot.rpg.get_user(username)
            self._show_detail_overlay(
                f"{display_name} / !wb ショップ",
                self._build_world_boss_shop_lines(display_name, user),
            )
            await ctx.reply(f"{display_name} 交換冊数は1以上で指定してください。 `!wb 交換 闘気 2`")
            return

        ok, msg = self.bot.rpg.exchange_world_boss_skill_books(username, skill_name, quantity=quantity)
        if ok:
            self.bot.save_data()
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !wb ショップ",
            self._build_world_boss_shop_lines(display_name, user),
        )
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="wb参加", aliases=("wbjoin", "worldbossjoin", "ワールドボス参加"))
    async def world_boss_join(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.join_world_boss(username)
        if ok:
            self.bot.save_data()
            self._refresh_world_boss_overlay_live(display_name, username)
            await ctx.reply(f"{display_name} {msg}")
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="wb召喚", aliases=("wbsummon", "worldbosssummon"))
    async def world_boss_summon(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        ok, result = self.bot.rpg.summon_world_boss(username)
        payload = result if isinstance(result, dict) else {}
        reply = str(payload.get("reply", "") or "").strip() or "WBを召喚できませんでした。"
        headline = str(payload.get("headline", "") or "").strip()
        if ok:
            self.bot.save_data()
            publisher = getattr(self.bot, "publish_world_boss_spawn_notification", None)
            if callable(publisher) and headline:
                publisher(headline)
            await ctx.reply(reply)
            return
        await ctx.reply(f"{display_name} {reply}")

    @commands.command(name="wb離脱", aliases=("wbleave", "worldbossleave", "ワールドボス離脱"))
    async def world_boss_leave(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.leave_world_boss(username)
        if ok:
            self.bot.save_data()
            self._refresh_world_boss_overlay_live(display_name, username)
            await ctx.reply(f"{display_name} {msg}")
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="wb結果", aliases=("wbresult", "worldbossresult", "ワールドボス結果"))
    async def world_boss_result(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        result = self.bot.rpg.get_last_world_boss_result(username)
        if not isinstance(result, dict):
            await ctx.reply(f"{display_name} はまだ確認できるWB結果がありません。")
            return

        self._show_detail_overlay(
            f"{display_name} / !wb 結果",
            self._build_world_boss_result_lines(display_name, result),
        )
        await ctx.reply(self._build_world_boss_result_reply(display_name, result))

    @commands.command(name="wbランキング", aliases=("wbrank", "worldbossrank", "ワールドボスランキング"))
    async def world_boss_ranking(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        status = self.bot.rpg.get_world_boss_status(username)
        self._show_detail_overlay(
            f"{display_name} / !wb ランキング",
            self._build_world_boss_ranking_lines(display_name, status),
        )
        await ctx.reply(self._build_world_boss_ranking_reply(display_name, status))

    @commands.command(name="wb開始", aliases=("wbstart", "worldbossstart"))
    async def world_boss_start(self, ctx: commands.Context, *, boss_id: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        _, display_name = self._get_identity(ctx)
        selector = (boss_id or "").strip()
        resolved_boss_id: Optional[str] = None
        if selector:
            resolved_boss_id, available = self._resolve_world_boss_selector(selector)
            if not resolved_boss_id:
                if available:
                    await ctx.reply(
                        f"{display_name} WB番号またはboss_idを指定してください。 利用可能: {available}"
                    )
                    return
                await ctx.reply(f"{display_name} 利用可能なWBがありません。")
                return

        ok, msg = self.bot.rpg.start_world_boss(resolved_boss_id)
        if ok:
            self.bot.save_data()
            publisher = getattr(self.bot, "publish_world_boss_spawn_notification", None)
            if callable(publisher):
                publisher(msg)
            await ctx.reply(msg)
            return

        available = self._format_world_boss_selector_options()
        if available:
            await ctx.reply(f"{display_name} {msg} / 利用可能: {available}")
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="wb終了", aliases=("wbstop", "worldbossstop"))
    async def world_boss_stop(self, ctx: commands.Context) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        _, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.stop_world_boss()
        if ok:
            self.bot.save_data()
            await ctx.reply(msg)
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="wbスキップ", aliases=("wbskip", "worldbossskip"))
    async def world_boss_skip(self, ctx: commands.Context) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        _, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.skip_world_boss()
        if ok:
            self.bot.save_data()
            await ctx.reply(msg)
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(
        name="読み上げID",
        aliases=("voicevoxid", "vvid", "speakerid", "ttsid"),
    )
    async def set_voicevox_speaker_id(
        self,
        ctx: commands.Context,
        speaker_id: Optional[str] = None,
    ) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        get_speaker_id = getattr(self.bot, "get_rpg_voicevox_speaker_id", None)
        set_speaker_id = getattr(self.bot, "set_rpg_voicevox_speaker_id", None)

        current_id = 0
        if callable(get_speaker_id):
            try:
                current_id = max(0, int(get_speaker_id()))
            except Exception:
                current_id = 0

        safe_text = str(speaker_id or "").strip()
        if not safe_text:
            await ctx.reply(
                f"RPG読み上げVOICEVOX ID は {current_id} です。"
                " `!管理 読み上げID <数字>` で変更できます。"
            )
            return

        try:
            next_id = max(0, int(safe_text))
        except ValueError:
            await ctx.reply("`!管理 読み上げID <数字>` で指定してください。")
            return

        applied_id = next_id
        if callable(set_speaker_id):
            applied_id = max(0, int(set_speaker_id(next_id)))
        if hasattr(self.bot, "save_data"):
            self.bot.save_data()
        await ctx.reply(f"RPG読み上げVOICEVOX ID を {applied_id} に変更しました。")

    @commands.command(
        name="読み上げ話者",
        aliases=("voicevoxspeaker", "vvspeaker", "speakername"),
    )
    async def set_voicevox_speaker_name(
        self,
        ctx: commands.Context,
        *,
        speaker_query: Optional[str] = None,
    ) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        get_speaker_id = getattr(self.bot, "get_rpg_voicevox_speaker_id", None)
        get_speaker_label = getattr(self.bot, "get_rpg_voicevox_speaker_label", None)
        find_style = getattr(self.bot, "find_rpg_voicevox_style", None)
        set_speaker_id = getattr(self.bot, "set_rpg_voicevox_speaker_id", None)

        current_id = 0
        if callable(get_speaker_id):
            try:
                current_id = max(0, int(get_speaker_id()))
            except Exception:
                current_id = 0

        current_label = f"VOICEVOX ID {current_id}"
        if callable(get_speaker_label):
            try:
                current_label = str(get_speaker_label() or current_label).strip() or current_label
            except Exception:
                pass

        safe_query = nfkc(str(speaker_query or "")).strip()
        if not safe_query:
            await ctx.reply(
                f"RPG読み上げ話者は {current_label} (ID:{current_id}) です。"
                " `!管理 読み上げ話者 <話者名>` で変更できます。"
            )
            return

        if not callable(find_style) or not callable(set_speaker_id):
            await ctx.reply("このボットでは話者名切替に対応していません。")
            return

        try:
            selected_style, candidates = find_style(safe_query)
        except Exception:
            await ctx.reply(
                "VOICEVOX から話者一覧を取得できませんでした。"
                " エンジン起動と接続先を確認してください。"
            )
            return

        if not selected_style:
            if candidates:
                candidate_labels = " / ".join(
                    str(candidate.get("label", "")).strip()
                    for candidate in candidates[:5]
                    if str(candidate.get("label", "")).strip()
                )
                if candidate_labels:
                    await ctx.reply(
                        "候補が複数あります。"
                        f" {candidate_labels} / `!管理 読み上げ話者 <話者名 スタイル名>` で絞ってください。"
                    )
                    return
            await ctx.reply(
                "該当する話者が見つかりませんでした。"
                " `!管理 読み上げ話者 ずんだもん` や `!管理 読み上げ話者 ずんだもん あまあま` のように指定してください。"
            )
            return

        label = str(selected_style.get("label", "")).strip() or safe_query
        try:
            applied_id = max(
                0,
                int(
                    set_speaker_id(
                        int(selected_style.get("style_id", 0)),
                        label=label,
                    )
                ),
            )
        except TypeError:
            applied_id = max(0, int(set_speaker_id(int(selected_style.get("style_id", 0)))))
        if hasattr(self.bot, "save_data"):
            self.bot.save_data()
        await ctx.reply(f"RPG読み上げ話者を {label} (ID:{applied_id}) に変更しました。")

    @commands.command(name="管理")
    async def manage(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if await self._dispatch_subcommand(
            ctx,
            subcommand,
            remainder,
            [
                (
                    {"読み上げid", "voicevoxid", "vvid", "speakerid", "ttsid"},
                    self.set_voicevox_speaker_id.callback,
                    "speaker_id",
                ),
                (
                    {"読み上げ話者", "voicevoxspeaker", "vvspeaker", "speakername"},
                    self.set_voicevox_speaker_name.callback,
                    "speaker_query",
                ),
                ({"ping"}, self.ping.callback, None),
            ],
        ):
            return
        if subcommand in {"debug", "dbg"}:
            debug_command, debug_remainder = self._split_subcommand(remainder)
            if debug_command in {"heal"}:
                await self.debugheal.callback(self, ctx, target_name=debug_remainder or None)
                return
            if debug_command in {"down"}:
                await self.debugdown.callback(self, ctx, target_name=debug_remainder or None)
                return
            if debug_command in {"gold", "potion", "exp"}:
                amount, target_name = self._parse_int_argument(debug_remainder)
                if amount is None:
                    _, display_name = self._get_identity(ctx)
                    await ctx.reply(
                        f"{display_name} `!管理 debug {debug_command} <数値> [対象名]` で指定してください。"
                    )
                    return
                if debug_command == "gold":
                    await self.debuggold.callback(self, ctx, amount=amount, target_name=target_name or None)
                    return
                if debug_command == "potion":
                    await self.debugpotion.callback(self, ctx, amount=amount, target_name=target_name or None)
                    return
                await self.debugexp.callback(self, ctx, amount=amount, target_name=target_name or None)
                return

        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        await ctx.reply(
            self._show_help_topic(
                display_name,
                "!管理",
                self._build_manage_help_lines(),
                "管理ヘルプ",
            )
        )

    @commands.command(name="探索")
    async def explore(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if await self._dispatch_subcommand(
            ctx,
            subcommand,
            remainder,
            [
                ({"開始", "start", "explore"}, self.explore_start.callback, "area"),
                ({"準備", "prep", "prepare"}, self.explore_prepare.callback, "slot_text"),
                ({"自動", "autostart", "loop", "loopstart"}, self.auto_repeat_start.callback, "area"),
                ({"停止", "stop", "autostop", "loopstop"}, self.stop_auto_repeat.callback, None),
                ({"結果", "result", "claim", "詳細", "detail"}, self.explore_result.callback, None),
                ({"前回", "last", "last_result"}, self.last_result.callback, None),
                ({"履歴", "history"}, self.history.callback, None),
                ({"戦利品", "loot", "drops"}, self.loot.callback, None),
                ({"戦闘", "battle", "battle_detail"}, self.battle_detail.callback, "page_text"),
            ],
        ):
            return
        if subcommand in {"help", "使い方"}:
            pass
        elif self._looks_like_exploration_shortcut(args):
            await self.explore_start.callback(self, ctx, area=args)
            return
        elif subcommand:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!探索 <エリア>` `!探索 準備 武器` `!探索 結果` を使ってください。"
            )
            return

        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        await ctx.reply(
            self._show_help_topic(
                display_name,
                "!探索",
                self._build_explore_help_lines(),
                "探索ヘルプ",
            )
        )

    @commands.command(name="探索開始", aliases=("explore", "start"))
    async def explore_start(self, ctx: commands.Context, *, area: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)

        ok, msg = self.bot.rpg.start_exploration(username, area)
        self.bot.save_data()

        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="探索準備", aliases=("exploreprep", "prep"))
    async def explore_prepare(self, ctx: commands.Context, *, slot_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        slot = self._normalize_slot(slot_text)
        user = self.bot.rpg.get_user(username)

        if not slot:
            current_status = self.bot.rpg.format_exploration_preparation_status(user)
            await ctx.reply(
                f"{display_name} `!探索 準備 武器|防具|装飾|靴` で次の探索1回だけ強化できます。"
                f" 待機中:{current_status}"
            )
            return

        ok, msg = self.bot.rpg.prepare_exploration(username, slot)
        if ok:
            self.bot.save_data()
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="自動周回開始", aliases=("autostart", "loopstart"))
    async def auto_repeat_start(self, ctx: commands.Context, *, area: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        request_text = "自動"
        if str(area or "").strip():
            request_text = f"自動 {area}"

        ok, msg = self.bot.rpg.start_exploration(username, request_text)
        self.bot.save_data()

        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="探索地", aliases=("areas", "area"))
    async def areas(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !攻略 エリア",
            self._build_area_guide_lines(display_name, user),
        )
        await ctx.reply(self._build_detail_hint_reply(display_name, "攻略エリア"))

    @commands.command(name="探索診断", aliases=("diagnosis", "diag"))
    async def exploration_diagnosis(self, ctx: commands.Context, *, request_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        diagnosis_request = request_text if str(request_text or "").strip() else self._get_default_diagnosis_request(user)
        diagnosis = self.bot.rpg.build_exploration_diagnosis(user, diagnosis_request)
        self._show_detail_overlay(
            f"{display_name} / !攻略 診断",
            self._build_exploration_diagnosis_lines(display_name, user, diagnosis),
        )
        mode = diagnosis.get("mode") or self.bot.rpg.resolve_exploration_mode(None)
        area_name = str(diagnosis.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip()
        if area_name not in AREAS:
            area_name = DEFAULT_AREA
        await ctx.reply(
            self._build_detail_hint_reply(
                display_name,
                "攻略診断",
                f"{mode['label']} {area_name}",
                f"危険度:{diagnosis.get('danger_label', '安定')}",
            )
        )

    @commands.command(name="ヘルプ", aliases=("rpghelp", "guide", "使い方"))
    async def rpg_help(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        topic, _ = self._split_subcommand(args)
        detail_lines = self._build_rpg_help_lines()
        reply_label = "RPGヘルプ"
        if topic in {"状態", "me", "status"}:
            detail_lines = self._build_status_help_lines()
            reply_label = "状態ヘルプ"
        elif topic in {"探索", "explore"}:
            detail_lines = self._build_explore_help_lines()
            reply_label = "探索ヘルプ"
        elif topic in {"装備", "equip"}:
            detail_lines = self._build_equip_help_lines()
            reply_label = "装備ヘルプ"
        elif topic in {"スキル", "skills", "skill"}:
            detail_lines = self._build_skill_help_lines()
            reply_label = "スキルヘルプ"
        elif topic in {"称号", "title", "titles"}:
            detail_lines = self._build_title_help_lines()
            reply_label = "称号ヘルプ"
        elif topic in {"攻略", "advice", "next"}:
            detail_lines = self._build_advice_help_lines()
            reply_label = "攻略ヘルプ"
        elif topic in {"wb", "worldboss", "ワールドボス"}:
            detail_lines = self._build_world_boss_help_lines()
            reply_label = "WBヘルプ"
        elif topic in {"discord", "ディスコード", "invite", "招待", "参加url"}:
            detail_lines = self._build_discord_help_lines()
            reply_label = "Discord案内"
        elif topic in {"管理", "admin", "debug"}:
            detail_lines = self._build_manage_help_lines()
            reply_label = "管理ヘルプ"
        await ctx.reply(
            self._show_help_topic(
                display_name,
                "!ヘルプ",
                detail_lines,
                reply_label,
            )
        )

    @commands.command(name="前回結果", aliases=("last_result", "last"))
    async def last_result(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        explore = user.get("explore", {})
        if (
            explore.get("state") == "exploring"
            and not bool(explore.get("auto_repeat", False))
            and max(0, int(explore.get("ends_at", 0) - now_ts())) <= 0
        ):
            await ctx.reply(f"{display_name} の最新探索は未受取です。 `!探索 結果` で受け取ってください。")
            return

        result = user.get("last_exploration_result")
        if not isinstance(result, dict):
            await ctx.reply(f"{display_name} はまだ確認できる前回結果がありません。")
            return

        self._show_detail_overlay(
            f"{display_name} / !探索 前回",
            self._build_exploration_result_lines(
                display_name,
                result,
                command_name="!探索 前回",
                detail_state_label="前回結果",
            ),
        )
        await ctx.reply(
            self._build_exploration_result_reply_message(
                display_name,
                result,
                claimed_now=False,
                current_level=self.bot.rpg.get_adventure_level(user),
                current_gold=int(user.get("gold", 0)),
            )
        )

    @commands.command(name="履歴", aliases=("history",))
    async def history(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        history = self.bot.rpg.get_exploration_history(user)
        if not history:
            await ctx.reply(f"{display_name} はまだ探索履歴がありません。")
            return

        self._show_detail_overlay(
            f"{display_name} / !探索 履歴",
            self._build_history_detail_lines(display_name, history),
        )
        await ctx.reply(self._build_detail_hint_reply(display_name, f"履歴 {len(history)}件"))

    @commands.command(name="戦利品", aliases=("loot", "drops"))
    async def loot(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        history = self.bot.rpg.get_exploration_history(user)
        if not history:
            await ctx.reply(f"{display_name} はまだ確認できる戦利品がありません。")
            return

        latest = history[0]
        loot_summary = self._build_history_loot_summary(latest)
        if not loot_summary:
            await ctx.reply(f"{display_name} の直近探索に目立つ戦利品はありません。")
            return

        lines = [
            "コマンド: !探索 戦利品",
            f"ユーザー: {display_name}",
            f"対象: {self._build_history_entry_line(latest, include_loot=False)}",
            f"戦利品: {loot_summary}",
        ]
        self._show_detail_overlay(f"{display_name} / !探索 戦利品", lines)
        await ctx.reply(self._build_detail_hint_reply(display_name, "直近戦利品"))

    @commands.command(name="攻略", aliases=("advice", "next"))
    async def advice(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if await self._dispatch_subcommand(
            ctx,
            subcommand,
            remainder,
            [
                ({"順", "route", "progression"}, self.progression_help.callback, None),
                ({"診断", "diag", "diagnosis"}, self.exploration_diagnosis.callback, "request_text"),
                ({"エリア", "area", "areas"}, self.areas.callback, None),
            ],
        ):
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            await ctx.reply(
                self._show_help_topic(
                    display_name,
                    "!攻略",
                    self._build_advice_help_lines(),
                    "攻略ヘルプ",
                )
            )
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!攻略` `!攻略 順` `!攻略 診断 <モード エリア>` `!攻略 エリア` を使ってください。"
            )
            return

        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        recommendation, changed = self._build_advice_recommendation(username, user)
        summary = str(recommendation.get("summary", "") or "").strip() or "おすすめ行動なし"
        if changed:
            self.bot.save_data()

        self._show_detail_overlay(
            f"{display_name} / !攻略",
            self._build_recommendation_detail_lines(display_name, user, recommendation),
        )
        await ctx.reply(self._build_detail_hint_reply(display_name, "攻略", summary))

    @commands.command(name="攻略順", aliases=("progression", "route"))
    async def progression_help(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        self.bot.rpg.get_user(username)
        self._show_detail_overlay(
            f"{display_name} / !攻略 順",
            self._build_progression_help_lines(),
        )
        await ctx.reply(self._build_detail_hint_reply(display_name, "攻略順"))

    @commands.command(name="自動周回停止", aliases=("autostop", "loopstop"))
    async def stop_auto_repeat(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.stop_auto_repeat(username)
        if ok:
            self.bot.save_data()
            await ctx.reply(f"{display_name} {msg}")
            return
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="探索結果", aliases=("claim", "result"))
    async def explore_result(self, ctx: commands.Context) -> None:
        await self._handle_exploration_result_command(ctx)

    @commands.command(name="探索詳細", aliases=("explore_detail", "detail"))
    async def explore_detail(self, ctx: commands.Context, *, page_text: Optional[str] = None) -> None:
        await self._handle_exploration_result_command(ctx)

    @commands.command(name="戦闘詳細", aliases=("battle_detail",))
    async def battle_detail(self, ctx: commands.Context, *, page_text: Optional[str] = None) -> None:
        await self._handle_battle_detail_command(ctx, page_text=page_text)

    @commands.command(name="バッグ", aliases=("bag", "inventory"))
    async def bag(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        bag = self.bot.rpg.get_sorted_bag_items(user)
        materials_text = self.bot.rpg.format_material_inventory(user)
        self._show_detail_overlay(
            f"{display_name} / !装備 バッグ",
            self._build_inventory_detail_lines(display_name, user),
        )

        await ctx.reply(
            self._build_detail_hint_reply(
                display_name,
                f"装備袋:{len(bag)}件" if bag else "装備袋:0件",
                f"素材:{materials_text}",
            )
        )

    @commands.command(name="素材", aliases=("materials", "mat"))
    async def materials(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        await ctx.reply(f"{display_name} 素材 / {self.bot.rpg.format_material_inventory(user)}")

    @commands.command(name="装備", aliases=("equip",))
    async def equip(self, ctx: commands.Context, *, args: Optional[str] = None) -> None:
        subcommand, remainder = self._split_subcommand(args)
        if await self._dispatch_subcommand(
            ctx,
            subcommand,
            remainder,
            [
                ({"バッグ", "bag", "inventory"}, self.bag.callback, None),
                ({"素材", "material", "materials", "mat"}, self.materials.callback, None),
                ({"整理", "organize", "更新", "装備更新", "update", "update_equip"}, self.organize.callback, None),
                ({"保護", "lock", "keep"}, self.protect_item.callback, "reference_text"),
                ({"保護解除", "unlock", "unkeep"}, self.unprotect_item.callback, "reference_text"),
                ({"強化", "enhance"}, self.enhance.callback, "slot_text"),
                ({"自動強化", "autoenhance", "全強化"}, self.auto_enhance.callback, "slot_text"),
                ({"エンチャント", "エンチャ", "enchant"}, self.enchant.callback, "slot_text"),
            ],
        ):
            return
        if subcommand in {"help", "使い方"}:
            username, display_name = self._get_identity(ctx)
            self.bot.rpg.get_user(username)
            await ctx.reply(
                self._show_help_topic(
                    display_name,
                    "!装備",
                    self._build_equip_help_lines(),
                    "装備ヘルプ",
                )
            )
            return
        if subcommand:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!装備 バッグ` `!装備 整理` `!装備 強化 武器` を使ってください。"
            )
            return

        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)

        power = self.bot.rpg.get_total_power(user)
        explore = user.get("explore", {})
        active_mode = self.bot.rpg.resolve_exploration_mode(
            explore.get("mode") if explore.get("state") == "exploring" else None
        )
        atk, defense = self.bot.rpg.get_player_combat_stats(user, active_mode["key"])
        speed = getattr(self.bot.rpg, "get_player_speed", lambda _user: 0)(user)
        weapon_bonus = self._format_weapon_bonus(user)
        ring_bonus = self._format_ring_bonus(user)
        weapon_enchant = self._format_slot_enchant_status(user, "weapon")
        armor_enchant = self._format_slot_enchant_status(user, "armor")
        ring_enchant = self._format_slot_enchant_status(user, "ring")
        shoes_enchant = self._format_slot_enchant_status(user, "shoes")

        await ctx.reply(
            f"{display_name} 装備 / {self._format_equipment_summary(user)} / "
            f"A:{atk} / D:{defense} / S:{speed} / 戦力{power} / "
            f"致死耐性:{self._format_guard_count_for_user(user)} / "
            f"武器E:{weapon_enchant} / 防具E:{armor_enchant} / 装飾E:{ring_enchant} / 靴E:{shoes_enchant} / "
            f"武器補正:{weapon_bonus} / 装飾補正:{ring_bonus}"
        )

    async def _run_organize_command(
        self,
        ctx: commands.Context,
        *,
        command_label: str,
        reply_label: str,
    ) -> None:
        username, display_name = self._get_identity(ctx)
        user_before = self.bot.rpg.get_user(username)
        before_power = self.bot.rpg.get_total_power(user_before)
        before_bag_count = len(user_before.get("bag", []))
        before_weapon = self.bot.rpg.format_equipped_item(user_before, "weapon")
        before_armor = self.bot.rpg.format_equipped_item(user_before, "armor")
        before_ring = self.bot.rpg.format_equipped_item(user_before, "ring")
        before_shoes = self.bot.rpg.format_equipped_item(user_before, "shoes")

        changed = self.bot.rpg.autoequip_best(username)
        sold_count, gold = self.bot.rpg.sell_all_bag_items(username)

        user_after = self.bot.rpg.get_user(username)
        after_power = self.bot.rpg.get_total_power(user_after)
        after_bag_count = len(user_after.get("bag", []))
        after_weapon = self.bot.rpg.format_equipped_item(user_after, "weapon")
        after_armor = self.bot.rpg.format_equipped_item(user_after, "armor")
        after_ring = self.bot.rpg.format_equipped_item(user_after, "ring")
        after_shoes = self.bot.rpg.format_equipped_item(user_after, "shoes")
        recommendation = self._build_recommendation(user_after)
        recommendation_summary = str(recommendation.get("summary", "") or "").strip() or "次のおすすめはありません"
        user_after["last_recommendation"] = {
            "action": str(recommendation.get("action", "") or "").strip(),
            "summary": recommendation_summary,
            "reason": str(recommendation.get("reason", "") or "").strip(),
            "area": str(recommendation.get("area", "") or "").strip(),
            "generated_at": now_ts(),
        }
        self.bot.save_data()

        has_changes = bool(changed or sold_count > 0 or before_power != after_power)
        detail_lines = self._build_organize_detail_lines(
            command_label=command_label,
            display_name=display_name,
            before_power=before_power,
            after_power=after_power,
            before_bag_count=before_bag_count,
            after_bag_count=after_bag_count,
            before_weapon=before_weapon,
            after_weapon=after_weapon,
            before_armor=before_armor,
            after_armor=after_armor,
            before_ring=before_ring,
            after_ring=after_ring,
            before_shoes=before_shoes,
            after_shoes=after_shoes,
            sold_count=sold_count,
            gold=gold,
            recommendation_summary=recommendation_summary,
            has_changes=has_changes,
        )
        self._show_detail_overlay(f"{display_name} / {command_label}", detail_lines)

        if has_changes:
            await ctx.reply(
                self._build_detail_hint_reply(
                    display_name,
                    f"{reply_label}完了",
                    f"戦力{before_power}->{after_power}",
                )
            )
            return

        await ctx.reply(
            self._build_detail_hint_reply(display_name, f"{reply_label}完了", "変化なし")
        )

    async def _run_auto_enhance_command(
        self,
        ctx: commands.Context,
        *,
        command_label: str,
        slot: Optional[str],
    ) -> None:
        username, display_name = self._get_identity(ctx)
        user_before = self.bot.rpg.get_user(username)
        before_power = self.bot.rpg.get_total_power(user_before)
        before_gold = max(0, int(user_before.get("gold", 0)))
        before_weapon = self.bot.rpg.format_equipped_item(user_before, "weapon")
        before_armor = self.bot.rpg.format_equipped_item(user_before, "armor")
        before_ring = self.bot.rpg.format_equipped_item(user_before, "ring")
        before_shoes = self.bot.rpg.format_equipped_item(user_before, "shoes")
        before_materials = dict(self.bot.rpg.get_material_inventory(user_before))

        target_slots = [slot] if slot else self._get_slot_order()
        summary = self.bot.rpg.auto_enhance_equipped_items(username, slots=target_slots)

        user_after = self.bot.rpg.get_user(username)
        after_power = self.bot.rpg.get_total_power(user_after)
        after_gold = max(0, int(user_after.get("gold", 0)))
        after_weapon = self.bot.rpg.format_equipped_item(user_after, "weapon")
        after_armor = self.bot.rpg.format_equipped_item(user_after, "armor")
        after_ring = self.bot.rpg.format_equipped_item(user_after, "ring")
        after_shoes = self.bot.rpg.format_equipped_item(user_after, "shoes")

        detail_summary = dict(summary)
        detail_summary["before_materials"] = before_materials
        detail_summary["after_materials"] = dict(self.bot.rpg.get_material_inventory(user_after))
        detail_lines = self._build_auto_enhance_detail_lines(
            command_label=command_label,
            display_name=display_name,
            before_power=before_power,
            after_power=after_power,
            before_gold=before_gold,
            after_gold=after_gold,
            before_weapon=before_weapon,
            after_weapon=after_weapon,
            before_armor=before_armor,
            after_armor=after_armor,
            before_ring=before_ring,
            after_ring=after_ring,
            before_shoes=before_shoes,
            after_shoes=after_shoes,
            summary=detail_summary,
        )
        self._show_detail_overlay(f"{display_name} / {command_label}", detail_lines)

        if bool(summary.get("attempted", False)):
            self.bot.save_data()

        await ctx.reply(
            self._build_auto_enhance_reply_message(
                display_name,
                detail_summary,
                before_power=before_power,
                after_power=after_power,
            )
        )

    @commands.command(name="保護", aliases=("lock", "keep"))
    async def protect_item(self, ctx: commands.Context, *, reference_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        item, error = self._resolve_bag_reference(user, reference_text)
        if error or not item:
            await ctx.reply(f"{display_name} {error or '保護対象を指定してください。'}")
            return

        item_id = str(item.get("item_id", "") or "").strip()
        if not item_id:
            await ctx.reply(f"{display_name} この装備はまだ保護できません。")
            return

        changed = self.bot.rpg.set_item_protection(username, item_id, True)
        if changed:
            self.bot.save_data()
            await ctx.reply(
                f"{display_name} 保護設定 / {self.bot.rpg.format_item_brief(item)} / id:{item_id}"
            )
            return

        await ctx.reply(f"{display_name} その装備はすでに保護済みです。")

    @commands.command(name="保護解除", aliases=("unlock", "unkeep"))
    async def unprotect_item(self, ctx: commands.Context, *, reference_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        user = self.bot.rpg.get_user(username)
        item, error = self._resolve_bag_reference(user, reference_text)
        if error or not item:
            await ctx.reply(f"{display_name} {error or '保護解除対象を指定してください。'}")
            return

        item_id = str(item.get("item_id", "") or "").strip()
        if not item_id:
            await ctx.reply(f"{display_name} この装備は保護解除できません。")
            return

        changed = self.bot.rpg.set_item_protection(username, item_id, False)
        if changed:
            self.bot.save_data()
            await ctx.reply(
                f"{display_name} 保護解除 / {self.bot.rpg.format_item_brief(item)} / id:{item_id}"
            )
            return

        await ctx.reply(f"{display_name} その装備は保護されていません。")

    @commands.command(name="整理", aliases=("organize",))
    async def organize(self, ctx: commands.Context) -> None:
        await self._run_organize_command(
            ctx,
            command_label="!装備 整理",
            reply_label="整理",
        )

    @commands.command(name="装備更新", aliases=("update_equip",))
    async def update_equip(self, ctx: commands.Context) -> None:
        await self._run_organize_command(
            ctx,
            command_label="!装備 整理",
            reply_label="整理",
        )

    @commands.command(name="ポーション購入", aliases=("buy_potion", "potion"))
    async def buy_potion(self, ctx: commands.Context, qty: Optional[int] = None) -> None:
        username, display_name = self._get_identity(ctx)
        ok, msg = self.bot.rpg.buy_potions(username, qty)
        if ok:
            self.bot.save_data()

        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="強化", aliases=("enhance",))
    async def enhance(self, ctx: commands.Context, *, slot_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        slot = self._normalize_slot(slot_text)

        if not slot:
            await ctx.reply(
                f"{display_name} `!装備 強化 武器|防具|装飾|靴` で装備中アイテムを強化できます。"
            )
            return

        attempted, msg = self.bot.rpg.enhance_equipped_item(username, slot)
        if attempted:
            self.bot.save_data()
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="自動強化", aliases=("autoenhance", "全強化"))
    async def auto_enhance(self, ctx: commands.Context, *, slot_text: Optional[str] = None) -> None:
        slot_text = (slot_text or "").strip()
        slot = self._normalize_slot(slot_text) if slot_text else None

        if slot_text and not slot:
            username, display_name = self._get_identity(ctx)
            await ctx.reply(
                f"{display_name} `!装備 自動強化` か `!装備 自動強化 武器|防具|装飾|靴` を使ってください。"
            )
            return

        command_label = "!装備 自動強化"
        if slot:
            command_label = f"!装備 自動強化 {SLOT_LABEL.get(slot, slot)}"
        await self._run_auto_enhance_command(
            ctx,
            command_label=command_label,
            slot=slot,
        )

    @commands.command(name="エンチャント", aliases=("enchant", "エンチャ"))
    async def enchant(self, ctx: commands.Context, *, slot_text: Optional[str] = None) -> None:
        username, display_name = self._get_identity(ctx)
        slot = self._normalize_slot(slot_text)

        if not slot:
            await ctx.reply(
                f"{display_name} `!装備 エンチャント 武器|防具|装飾|靴` で装備中アイテムに特殊効果を付与できます。"
            )
            return

        attempted, msg = self.bot.rpg.enchant_equipped_item(username, slot)
        if attempted:
            self.bot.save_data()
        await ctx.reply(f"{display_name} {msg}")

    @commands.command(name="蘇生", aliases=("revive",))
    async def revive(self, ctx: commands.Context) -> None:
        username, display_name = self._get_identity(ctx)
        _, msg = self.bot.rpg.revive_user(username)
        self.bot.save_data()
        await ctx.reply(msg)

    @commands.command(name="debugheal")
    async def debugheal(self, ctx: commands.Context, target_name: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        target, display_name = self._get_target_identity(ctx, target_name)
        ok, msg = self.bot.rpg.debug_heal_user(target)
        self.bot.save_data()
        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="debuggold")
    async def debuggold(self, ctx: commands.Context, amount: int, target_name: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        target, display_name = self._get_target_identity(ctx, target_name)
        ok, msg = self.bot.rpg.debug_add_gold(target, amount)
        self.bot.save_data()
        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="debugpotion")
    async def debugpotion(self, ctx: commands.Context, amount: int, target_name: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        target, display_name = self._get_target_identity(ctx, target_name)
        ok, msg = self.bot.rpg.debug_add_potions(target, amount)
        self.bot.save_data()
        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="debugexp")
    async def debugexp(self, ctx: commands.Context, amount: int, target_name: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        target, display_name = self._get_target_identity(ctx, target_name)
        ok, msg = self.bot.rpg.debug_add_adventure_exp(target, amount)
        self.bot.save_data()
        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)

    @commands.command(name="debugdown")
    async def debugdown(self, ctx: commands.Context, target_name: Optional[str] = None) -> None:
        if not self._is_owner(ctx):
            await ctx.reply("このコマンドは配信者のみ使用できます。")
            return

        target, display_name = self._get_target_identity(ctx, target_name)
        ok, msg = self.bot.rpg.debug_down_user(target)
        self.bot.save_data()
        if ok:
            await ctx.reply(f"{display_name} {msg}")
        else:
            await ctx.reply(msg)
