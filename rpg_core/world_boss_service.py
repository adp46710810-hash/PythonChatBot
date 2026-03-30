from __future__ import annotations

from copy import deepcopy
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from .balance_data import AREAS, MATERIAL_LABELS, WORLD_BOSSES
from .stat_helpers import GAUGE_THRESHOLD, normalize_stats
from .utils import now_ts


WORLD_BOSS_HISTORY_LIMIT = 5
WORLD_BOSS_RECENT_LOG_LIMIT = 8
WORLD_BOSS_COOLDOWN_SEC = 30
WORLD_BOSS_PENDING_ANNOUNCEMENT_LIMIT = 4
WORLD_BOSS_AUTO_SPAWN_LEGACY_CHANCE = 0.30
WORLD_BOSS_AUTO_SPAWN_PITY_ROLLS = 3
WORLD_BOSS_AUTO_SPAWN_BASE_CHANCE = 0.04
WORLD_BOSS_AUTO_SPAWN_TIER_CHANCE_STEP = 0.02
WORLD_BOSS_AUTO_SPAWN_CLEAR_CHANCE_STEP = 0.03
WORLD_BOSS_AUTO_SPAWN_CLEAR_CHANCE_CAP = 0.18
WORLD_BOSS_AUTO_SPAWN_CHANCE_CAP = 0.50
WORLD_BOSS_JOIN_SEC_DEFAULT = 60
WORLD_BOSS_DURATION_SEC_DEFAULT = 180
WORLD_BOSS_HP_SCALE_LOG2_STEP = 0.90
WORLD_BOSS_SUMMON_MATERIAL_COST = 48
WORLD_BOSS_SUMMON_MATERIAL_PRIORITY = ("weapon", "armor", "ring", "shoes")
WORLD_BOSS_MAJOR_PHASE_THRESHOLDS = {75: ("phase_2", "PHASE 2"), 25: ("last_stand", "LAST STAND")}
WORLD_BOSS_OBJECTIVE_SCORE_CLEAR_BONUS = 5
WORLD_BOSS_QUIET_VISUAL_EVENT_KINDS = {"join", "late_join"}


class WorldBossService:
    def __init__(
        self,
        data: Dict[str, Any],
        user_service,
        battle_service,
        *,
        owner_username: str = "",
    ) -> None:
        self.data = data
        self.user_service = user_service
        self.battle_service = battle_service
        self.owner_username = str(owner_username or "").strip().lower()

    def _is_owner_rank_content_user(self, username: Optional[str]) -> bool:
        safe_username = str(username or "").strip().lower()
        return bool(self.owner_username) and safe_username == self.owner_username

    def _build_idle_state(self) -> Dict[str, Any]:
        return {
            "phase": "idle",
            "phase_id": "idle",
            "phase_label": "",
            "event_kind": "",
            "event_text": "",
            "boss_id": "",
            "boss": {},
            "participants": {},
            "current_hp": 0,
            "max_hp": 0,
            "boss_action_gauge": 0,
            "started_at": 0.0,
            "join_ends_at": 0.0,
            "ends_at": 0.0,
            "last_tick_at": 0.0,
            "tick_index": 0,
            "join_warning_sent": False,
            "battle_warning_sent": False,
            "aoe_thresholds_triggered": [],
            "enrage_announced": False,
            "cooldown_ends_at": 0.0,
            "start_participants": 0,
            "late_join_count": 0,
            "late_join_open": False,
            "leader_name": "",
            "leader_score": 0,
            "runner_up_name": "",
            "runner_up_score": 0,
            "leader_gap": 0,
            "recent_logs": [],
            "ranking": [],
            "last_result": {},
            "pending_announcements": [],
        }

    def _build_auto_spawn_progress(self) -> Dict[str, Any]:
        return {
            "claim_count": 0,
            "pending_rolls": [],
            "completed_cycles": 0,
            "last_cycle_completed_at": 0.0,
            "failed_rolls": 0,
            "area_boss_clear_counts": {},
            "last_trigger_area": "",
            "last_trigger_chance": 0.0,
        }

    def _calculate_auto_spawn_chance(self, area_name: str, boss_clear_count: int) -> float:
        safe_area_name = str(area_name or "").strip()
        area = AREAS.get(safe_area_name, {})
        tier = max(1, int(area.get("tier", 1) or 1))
        safe_clear_count = max(0, int(boss_clear_count))
        tier_bonus = max(0, tier - 1) * WORLD_BOSS_AUTO_SPAWN_TIER_CHANCE_STEP
        clear_bonus = min(
            WORLD_BOSS_AUTO_SPAWN_CLEAR_CHANCE_CAP,
            max(0, safe_clear_count - 1) * WORLD_BOSS_AUTO_SPAWN_CLEAR_CHANCE_STEP,
        )
        return min(
            WORLD_BOSS_AUTO_SPAWN_CHANCE_CAP,
            WORLD_BOSS_AUTO_SPAWN_BASE_CHANCE + tier_bonus + clear_bonus,
        )

    def _build_pending_auto_spawn_roll(
        self,
        area_name: Optional[str],
        *,
        boss_clear_count: int = 0,
        triggered_at: float = 0.0,
        legacy: bool = False,
    ) -> Dict[str, Any]:
        safe_area_name = str(area_name or "").strip()
        if safe_area_name not in AREAS:
            safe_area_name = ""
        safe_boss_clear_count = max(0, int(boss_clear_count))
        chance = (
            WORLD_BOSS_AUTO_SPAWN_LEGACY_CHANCE
            if legacy
            else self._calculate_auto_spawn_chance(safe_area_name, safe_boss_clear_count)
        )
        tier = 0
        if safe_area_name:
            tier = max(1, int(AREAS.get(safe_area_name, {}).get("tier", 1) or 1))
        return {
            "area_name": safe_area_name,
            "boss_clear_count": safe_boss_clear_count,
            "tier": tier,
            "chance": min(1.0, max(0.0, float(chance))),
            "triggered_at": float(triggered_at or 0.0),
            "legacy": bool(legacy),
        }

    def _normalize_pending_auto_spawn_roll(self, raw_roll: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_roll, dict):
            return None

        area_name = str(raw_roll.get("area_name", "") or "").strip()
        if area_name not in AREAS:
            area_name = ""
        boss_clear_count = max(0, int(raw_roll.get("boss_clear_count", 0) or 0))
        triggered_at = float(raw_roll.get("triggered_at", 0.0) or 0.0)
        legacy = bool(raw_roll.get("legacy", False))
        roll = self._build_pending_auto_spawn_roll(
            area_name,
            boss_clear_count=boss_clear_count,
            triggered_at=triggered_at,
            legacy=legacy,
        )
        chance = raw_roll.get("chance", roll["chance"])
        roll["chance"] = min(1.0, max(0.0, float(chance or 0.0)))
        tier = raw_roll.get("tier", roll["tier"])
        roll["tier"] = max(0, int(tier or 0))
        return roll

    def _reset_auto_spawn_pressure(self, progress: Dict[str, Any]) -> None:
        progress["claim_count"] = 0
        progress["pending_rolls"] = []
        progress["area_boss_clear_counts"] = {}

    def _ensure_user_world_boss_data(self, user: Dict[str, Any]) -> None:
        materials = user.get("world_boss_materials")
        if not isinstance(materials, dict):
            materials = {}
            user["world_boss_materials"] = materials
        normalized_materials: Dict[str, int] = {}
        for key, value in materials.items():
            safe_key = str(key or "").strip()
            if not safe_key:
                continue
            try:
                normalized_materials[safe_key] = max(0, int(value))
            except (TypeError, ValueError):
                normalized_materials[safe_key] = 0
        user["world_boss_materials"] = normalized_materials

        history = user.get("world_boss_history")
        if not isinstance(history, list):
            history = []
        user["world_boss_history"] = [
            entry for entry in history if isinstance(entry, dict)
        ][:WORLD_BOSS_HISTORY_LIMIT]

        records = user.get("world_boss_records")
        if not isinstance(records, dict):
            records = {}
        user["world_boss_records"] = {
            "entries": max(0, int(records.get("entries", 0) or 0)),
            "clears": max(0, int(records.get("clears", 0) or 0)),
            "mvp_count": max(0, int(records.get("mvp_count", 0) or 0)),
            "best_rank": max(0, int(records.get("best_rank", 0) or 0)),
            "best_damage": max(0, int(records.get("best_damage", 0) or 0)),
        }

        last_result = user.get("last_world_boss_result")
        if not isinstance(last_result, dict):
            user["last_world_boss_result"] = None

    def _sanitize_participant(self, username: str, participant: Dict[str, Any]) -> Dict[str, Any]:
        safe_username = str(username or "").lower().strip()
        safe_display_name = str(
            participant.get("display_name", self.user_service.get_display_name(safe_username, safe_username)) or ""
        ).strip() or safe_username
        safe_title_label = str(participant.get("title_label", "") or "").strip()
        active_ticks = max(0, int(participant.get("active_ticks", 0) or 0))
        total_damage = max(0, int(participant.get("total_damage", 0) or 0))
        legacy_contribution_score = max(0, int(participant.get("contribution_score", 0) or 0))
        contribution = self._sanitize_contribution_breakdown(
            participant.get("contribution", {}),
            legacy_total=legacy_contribution_score,
            active_ticks=active_ticks,
            total_damage=total_damage,
        )
        total_contribution_score = max(
            legacy_contribution_score,
            max(0, int(participant.get("total_contribution_score", 0) or 0)),
            self._sum_contribution_breakdown(contribution),
        )
        return {
            "username": safe_username,
            "display_name": safe_display_name,
            "title_label": safe_title_label,
            "joined_at": float(participant.get("joined_at", 0.0) or 0.0),
            "join_phase": str(participant.get("join_phase", "") or "").strip(),
            "snapshot_atk": max(1, int(participant.get("snapshot_atk", 1) or 1)),
            "snapshot_def": max(0, int(participant.get("snapshot_def", 0) or 0)),
            "snapshot_speed": max(1, int(participant.get("snapshot_speed", 100) or 100)),
            "snapshot_max_hp": max(1, int(participant.get("snapshot_max_hp", 1) or 1)),
            "snapshot_stats": normalize_stats(
                participant.get(
                    "snapshot_stats",
                    {
                        "atk": participant.get("snapshot_atk", 1),
                        "def": participant.get("snapshot_def", 0),
                        "speed": participant.get("snapshot_speed", 100),
                        "max_hp": participant.get("snapshot_max_hp", 1),
                    },
                )
            ),
            "base_stats": normalize_stats(
                participant.get(
                    "base_stats",
                    participant.get(
                        "snapshot_stats",
                        {
                            "atk": participant.get("snapshot_atk", 1),
                            "def": participant.get("snapshot_def", 0),
                            "speed": participant.get("snapshot_speed", 100),
                            "max_hp": participant.get("snapshot_max_hp", 1),
                        },
                    ),
                )
            ),
            "snapshot_crit_rate": min(
                1.0,
                max(0.0, float(participant.get("snapshot_crit_rate", 0.0) or 0.0)),
            ),
            "snapshot_crit_damage_multiplier": max(
                1.0,
                float(participant.get("snapshot_crit_damage_multiplier", 1.0) or 1.0),
            ),
            "current_hp": max(0, int(participant.get("current_hp", 0) or 0)),
            "alive": bool(participant.get("alive", False)),
            "respawn_at": float(participant.get("respawn_at", 0.0) or 0.0),
            "total_damage": total_damage,
            "active_ticks": active_ticks,
            "contribution": contribution,
            "total_contribution_score": total_contribution_score,
            "contribution_score": total_contribution_score,
            "times_downed": max(0, int(participant.get("times_downed", 0) or 0)),
            "last_damage": max(0, int(participant.get("last_damage", 0) or 0)),
            "last_critical": bool(participant.get("last_critical", False)),
            "action_gauge": max(0, int(participant.get("action_gauge", 0) or 0)),
            "active_skills": self.battle_service.normalize_auto_skills(participant.get("active_skills", [])),
            "skill_cooldowns": {
                str(skill_id or "").strip(): max(0, int(cooldown or 0))
                for skill_id, cooldown in dict(participant.get("skill_cooldowns", {})).items()
                if str(skill_id or "").strip()
            },
            "active_effects": [
                {
                    "skill_id": str(effect.get("skill_id", "") or "").strip(),
                    "name": str(effect.get("name", "") or "").strip(),
                    "stats": normalize_stats(effect.get("stats", {})),
                    "actions_left": max(0, int(effect.get("actions_left", 0) or 0)),
                }
                for effect in participant.get("active_effects", [])
                if isinstance(effect, dict) and max(0, int(effect.get("actions_left", 0) or 0)) > 0
            ],
        }

    def _sanitize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        phase = str(state.get("phase", "idle") or "idle").strip()
        if phase not in {"idle", "recruiting", "active", "cooldown"}:
            phase = "idle"
        state["phase"] = phase

        boss_id = str(state.get("boss_id", "") or "").strip()
        if boss_id and boss_id not in WORLD_BOSSES:
            boss_id = ""
        state["boss_id"] = boss_id

        boss = state.get("boss")
        if not isinstance(boss, dict):
            boss = {}
        if boss_id in WORLD_BOSSES:
            template = deepcopy(WORLD_BOSSES[boss_id])
            boss = {**template, **boss}
        state["boss"] = boss

        participants = state.get("participants")
        if not isinstance(participants, dict):
            participants = {}
        sanitized_participants: Dict[str, Dict[str, Any]] = {}
        for username, participant in participants.items():
            if not isinstance(participant, dict):
                continue
            safe_username = str(username or "").lower().strip()
            if not safe_username:
                continue
            sanitized_participants[safe_username] = self._sanitize_participant(
                safe_username,
                participant,
            )
        state["participants"] = sanitized_participants

        for key in (
            "current_hp",
            "max_hp",
            "tick_index",
            "boss_action_gauge",
            "start_participants",
            "late_join_count",
            "leader_score",
            "runner_up_score",
            "leader_gap",
        ):
            state[key] = max(0, int(state.get(key, 0) or 0))
        for key in ("started_at", "join_ends_at", "ends_at", "last_tick_at", "cooldown_ends_at"):
            state[key] = float(state.get(key, 0.0) or 0.0)
        for key in ("join_warning_sent", "battle_warning_sent", "enrage_announced", "late_join_open"):
            state[key] = bool(state.get(key, False))
        for key in ("phase_id", "phase_label", "event_kind", "event_text", "leader_name", "runner_up_name"):
            state[key] = str(state.get(key, "") or "").strip()

        thresholds = state.get("aoe_thresholds_triggered")
        if not isinstance(thresholds, list):
            thresholds = []
        state["aoe_thresholds_triggered"] = [
            int(threshold) for threshold in thresholds if isinstance(threshold, (int, float))
        ]

        recent_logs = state.get("recent_logs")
        if not isinstance(recent_logs, list):
            recent_logs = []
        state["recent_logs"] = [
            str(line).strip() for line in recent_logs if str(line).strip()
        ][-WORLD_BOSS_RECENT_LOG_LIMIT:]

        ranking = state.get("ranking")
        if not isinstance(ranking, list):
            ranking = []
        state["ranking"] = [
            entry for entry in ranking if isinstance(entry, dict)
        ][:10]

        last_result = state.get("last_result")
        if not isinstance(last_result, dict):
            last_result = {}
        state["last_result"] = last_result

        pending_announcements = state.get("pending_announcements")
        if not isinstance(pending_announcements, list):
            pending_announcements = []
        state["pending_announcements"] = [
            str(line).strip()
            for line in pending_announcements
            if str(line).strip()
        ][-WORLD_BOSS_PENDING_ANNOUNCEMENT_LIMIT:]
        self._refresh_visual_state(state)
        return state

    def get_auto_spawn_progress(self) -> Dict[str, Any]:
        progress = self.data.get("world_boss_progress")
        if not isinstance(progress, dict):
            progress = self._build_auto_spawn_progress()
            self.data["world_boss_progress"] = progress

        raw_claim_count = progress.get("claim_count", 0)
        progress["claim_count"] = max(0, int(raw_claim_count or 0))
        progress["failed_rolls"] = max(0, int(progress.get("failed_rolls", 0) or 0))
        raw_completed_cycles = progress.get(
            "completed_cycles",
            progress.get("completed_routes", 0),
        )
        progress["completed_cycles"] = max(0, int(raw_completed_cycles or 0))
        raw_last_cycle_completed_at = progress.get(
            "last_cycle_completed_at",
            progress.get("last_route_completed_at", 0.0),
        )
        progress["last_cycle_completed_at"] = float(raw_last_cycle_completed_at or 0.0)
        progress["last_trigger_area"] = str(progress.get("last_trigger_area", "") or "").strip()
        progress["last_trigger_chance"] = min(
            1.0,
            max(0.0, float(progress.get("last_trigger_chance", 0.0) or 0.0)),
        )

        raw_area_boss_clear_counts = progress.get("area_boss_clear_counts")
        if not isinstance(raw_area_boss_clear_counts, dict):
            raw_area_boss_clear_counts = {}
        area_boss_clear_counts: Dict[str, int] = {}
        for area_name, clear_count in raw_area_boss_clear_counts.items():
            safe_area_name = str(area_name or "").strip()
            if safe_area_name not in AREAS:
                continue
            area_boss_clear_counts[safe_area_name] = max(0, int(clear_count or 0))
        progress["area_boss_clear_counts"] = area_boss_clear_counts

        raw_pending_rolls = progress.get("pending_rolls", [])
        pending_rolls: List[Dict[str, Any]] = []
        if isinstance(raw_pending_rolls, list):
            for raw_roll in raw_pending_rolls:
                normalized_roll = self._normalize_pending_auto_spawn_roll(raw_roll)
                if normalized_roll:
                    pending_rolls.append(normalized_roll)
        else:
            legacy_pending_rolls = max(0, int(raw_pending_rolls or 0))
            for _ in range(legacy_pending_rolls):
                pending_rolls.append(
                    self._build_pending_auto_spawn_roll(
                        None,
                        legacy=True,
                    )
                )
        progress["pending_rolls"] = pending_rolls

        progress.pop("visited_areas", None)
        progress.pop("completed_routes", None)
        progress.pop("last_route_completed_at", None)
        return progress

    def get_state(self) -> Dict[str, Any]:
        state = self.data.get("world_boss")
        if not isinstance(state, dict):
            state = self._build_idle_state()
            self.data["world_boss"] = state
        return self._sanitize_state(state)

    def list_boss_templates(self) -> List[Dict[str, Any]]:
        return [deepcopy(WORLD_BOSSES[boss_id]) for boss_id in WORLD_BOSSES]

    def get_summon_material_cost(self) -> int:
        return max(1, int(WORLD_BOSS_SUMMON_MATERIAL_COST))

    def _get_summon_material_slot_order(self) -> List[str]:
        ordered_slots: List[str] = [
            slot_name
            for slot_name in WORLD_BOSS_SUMMON_MATERIAL_PRIORITY
            if slot_name in MATERIAL_LABELS
        ]
        ordered_slots.extend(
            slot_name
            for slot_name in MATERIAL_LABELS
            if slot_name not in ordered_slots
        )
        return ordered_slots

    def _format_summon_material_status(self, inventory: Dict[str, int]) -> str:
        return " / ".join(
            f"{MATERIAL_LABELS.get(slot_name, slot_name)} {max(0, int(inventory.get(slot_name, 0) or 0))}"
            for slot_name in self._get_summon_material_slot_order()
        )

    def _build_summon_material_spend_plan(
        self,
        inventory: Dict[str, int],
        *,
        cost: int,
    ) -> List[Tuple[str, int]]:
        safe_cost = max(0, int(cost))
        if safe_cost <= 0:
            return []

        ordered_slots = self._get_summon_material_slot_order()
        slot_rank = {slot_name: index for index, slot_name in enumerate(ordered_slots)}
        ranked_slots = sorted(
            ordered_slots,
            key=lambda slot_name: (
                -max(0, int(inventory.get(slot_name, 0) or 0)),
                slot_rank[slot_name],
            ),
        )

        remaining = safe_cost
        spend_plan: List[Tuple[str, int]] = []
        for slot_name in ranked_slots:
            available = max(0, int(inventory.get(slot_name, 0) or 0))
            if available <= 0:
                continue
            spend = min(available, remaining)
            if spend <= 0:
                continue
            spend_plan.append((slot_name, spend))
            remaining -= spend
            if remaining <= 0:
                break

        if remaining > 0:
            return []
        return spend_plan

    def _pick_boss_template(self, boss_id: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        safe_boss_id = str(boss_id or "").strip()
        if safe_boss_id in WORLD_BOSSES:
            return safe_boss_id, deepcopy(WORLD_BOSSES[safe_boss_id])
        fallback_id = next(iter(sorted(WORLD_BOSSES)), "")
        if not fallback_id:
            raise RuntimeError("No world boss templates are configured")
        return fallback_id, deepcopy(WORLD_BOSSES[fallback_id])

    def _pick_random_boss_template(self) -> Tuple[str, Dict[str, Any]]:
        boss_ids = sorted(WORLD_BOSSES)
        if not boss_ids:
            raise RuntimeError("No world boss templates are configured")
        weights = [
            max(0.001, float(WORLD_BOSSES.get(boss_id, {}).get("spawn_weight", 1.0) or 1.0))
            for boss_id in boss_ids
        ]
        selected_boss_id = random.choices(boss_ids, weights=weights, k=1)[0]
        return selected_boss_id, deepcopy(WORLD_BOSSES[selected_boss_id])

    def _push_recent_log(self, state: Dict[str, Any], line: str) -> None:
        safe_line = str(line or "").strip()
        if not safe_line:
            return
        logs = state.setdefault("recent_logs", [])
        logs.append(safe_line)
        del logs[:-WORLD_BOSS_RECENT_LOG_LIMIT]

    def _queue_announcement(self, state: Dict[str, Any], line: str) -> None:
        safe_line = str(line or "").strip()
        if not safe_line:
            return
        queue = state.setdefault("pending_announcements", [])
        queue.append(safe_line)
        del queue[:-WORLD_BOSS_PENDING_ANNOUNCEMENT_LIMIT]

    def _drain_announcements(self, state: Dict[str, Any]) -> List[str]:
        queue = state.get("pending_announcements")
        if not isinstance(queue, list):
            return []
        messages = [
            str(line).strip()
            for line in queue
            if str(line).strip()
        ]
        state["pending_announcements"] = []
        return messages

    def _build_participant_snapshot(
        self,
        username: str,
        *,
        joined_at: float,
        join_phase: str = "recruiting",
    ) -> Dict[str, Any]:
        user = self.user_service.get_user(username)
        display_name = self.user_service.get_display_name(username, username)
        title_label = self.user_service.get_active_title_label(user)
        player_stats = self.user_service.get_player_stats(user, None)
        crit_rate, crit_multiplier = self.user_service.get_weapon_crit_stats(user)
        active_skills = self.user_service.get_selected_active_skills(user)
        return {
            "username": username,
            "display_name": display_name,
            "title_label": title_label,
            "joined_at": joined_at,
            "join_phase": str(join_phase or "recruiting").strip(),
            "snapshot_atk": int(player_stats.get("atk", 1)),
            "snapshot_def": int(player_stats.get("def", 0)),
            "snapshot_speed": int(player_stats.get("speed", 100)),
            "snapshot_max_hp": int(player_stats.get("max_hp", user.get("max_hp", 1))),
            "snapshot_stats": normalize_stats(player_stats),
            "base_stats": normalize_stats(player_stats),
            "snapshot_crit_rate": crit_rate,
            "snapshot_crit_damage_multiplier": crit_multiplier,
            "current_hp": int(player_stats.get("max_hp", user.get("max_hp", 1))),
            "alive": True,
            "respawn_at": 0.0,
            "total_damage": 0,
            "active_ticks": 0,
            "contribution": self._sanitize_contribution_breakdown({}),
            "total_contribution_score": 0,
            "contribution_score": 0,
            "times_downed": 0,
            "last_damage": 0,
            "last_critical": False,
            "action_gauge": 0,
            "active_skills": self.battle_service.normalize_auto_skills(active_skills),
            "skill_cooldowns": {},
            "active_effects": [],
        }

    def _scale_boss_hp(self, base_hp: int, participant_count: int) -> int:
        safe_count = max(1, int(participant_count))
        scaled = int(
            round(
                int(base_hp)
                * (1.0 + (WORLD_BOSS_HP_SCALE_LOG2_STEP * math.log2(safe_count)))
            )
        )
        return max(int(base_hp), scaled)

    def _sanitize_contribution_breakdown(
        self,
        contribution: Any,
        *,
        legacy_total: int = 0,
        active_ticks: int = 0,
        total_damage: int = 0,
    ) -> Dict[str, int]:
        raw_contribution = contribution if isinstance(contribution, dict) else {}
        breakdown = {
            "damage_score": max(0, int(raw_contribution.get("damage_score", 0) or 0)),
            "support_score": max(0, int(raw_contribution.get("support_score", 0) or 0)),
            "survival_score": max(0, int(raw_contribution.get("survival_score", 0) or 0)),
            "objective_score": max(0, int(raw_contribution.get("objective_score", 0) or 0)),
        }
        if self._sum_contribution_breakdown(breakdown) <= 0 and legacy_total > 0:
            guessed_survival = max(0, int(active_ticks))
            guessed_damage = max(0, legacy_total - guessed_survival)
            if total_damage > 0:
                guessed_damage = max(guessed_damage, int(total_damage))
            breakdown["damage_score"] = guessed_damage
            breakdown["survival_score"] = guessed_survival
        return breakdown

    def _sum_contribution_breakdown(self, contribution: Dict[str, int]) -> int:
        return sum(
            max(0, int(contribution.get(key, 0) or 0))
            for key in ("damage_score", "support_score", "survival_score", "objective_score")
        )

    def _sync_participant_contribution(self, participant: Dict[str, Any]) -> None:
        contribution = self._sanitize_contribution_breakdown(
            participant.get("contribution", {}),
            legacy_total=max(0, int(participant.get("contribution_score", 0) or 0)),
            active_ticks=max(0, int(participant.get("active_ticks", 0) or 0)),
            total_damage=max(0, int(participant.get("total_damage", 0) or 0)),
        )
        total_contribution_score = self._sum_contribution_breakdown(contribution)
        participant["contribution"] = contribution
        participant["total_contribution_score"] = total_contribution_score
        participant["contribution_score"] = total_contribution_score

    def _add_participant_contribution(
        self,
        participant: Dict[str, Any],
        *,
        damage: int = 0,
        support: int = 0,
        survival: int = 0,
        objective: int = 0,
    ) -> None:
        contribution = self._sanitize_contribution_breakdown(
            participant.get("contribution", {}),
            legacy_total=max(0, int(participant.get("contribution_score", 0) or 0)),
            active_ticks=max(0, int(participant.get("active_ticks", 0) or 0)),
            total_damage=max(0, int(participant.get("total_damage", 0) or 0)),
        )
        contribution["damage_score"] = max(0, int(contribution.get("damage_score", 0) or 0)) + max(0, int(damage))
        contribution["support_score"] = max(0, int(contribution.get("support_score", 0) or 0)) + max(0, int(support))
        contribution["survival_score"] = max(0, int(contribution.get("survival_score", 0) or 0)) + max(0, int(survival))
        contribution["objective_score"] = max(0, int(contribution.get("objective_score", 0) or 0)) + max(0, int(objective))
        participant["contribution"] = contribution
        self._sync_participant_contribution(participant)

    def _estimate_support_score_from_skill(self, skill: Optional[Dict[str, Any]]) -> int:
        if not isinstance(skill, dict):
            return 0
        stats = normalize_stats(skill.get("stats", {}))
        nonzero_stat_count = sum(
            1 for key in ("atk", "def", "speed", "max_hp") if int(stats.get(key, 0) or 0) > 0
        )
        special_effect_count = len(
            [
                effect
                for effect in self.battle_service._normalize_special_effects(skill.get("special_effects", []))
                if isinstance(effect, dict)
            ]
        )
        action_gauge_bonus = 1 if self.battle_service.get_skill_action_gauge_bonus(skill) > 0 else 0
        raw_score = nonzero_stat_count + special_effect_count + action_gauge_bonus
        return max(1, raw_score)

    def _is_participant_reward_eligible(self, boss: Dict[str, Any], participant: Dict[str, Any]) -> bool:
        min_ticks = max(1, int(boss.get("min_participation_ticks", 1)))
        min_contribution = max(1, int(boss.get("min_contribution", 1)))
        active_ticks = max(0, int(participant.get("active_ticks", 0) or 0))
        contribution_score = max(
            0,
            int(participant.get("total_contribution_score", participant.get("contribution_score", 0)) or 0),
        )
        return active_ticks >= min_ticks and contribution_score >= min_contribution

    def _get_objective_score_bonus(self, boss: Dict[str, Any], *, cleared: bool) -> int:
        if not cleared:
            return 0
        raw_bonus = boss.get("objective_score_bonus")
        if raw_bonus is not None:
            try:
                return max(0, int(raw_bonus))
            except (TypeError, ValueError):
                return WORLD_BOSS_OBJECTIVE_SCORE_CLEAR_BONUS
        return WORLD_BOSS_OBJECTIVE_SCORE_CLEAR_BONUS

    def _should_highlight_race(self, state: Dict[str, Any], *, now: Optional[float] = None) -> bool:
        if str(state.get("phase", "idle") or "idle").strip() != "active":
            return False
        phase_id = str(state.get("phase_id", "") or "").strip()
        if phase_id == "last_stand":
            return True
        if bool(state.get("battle_warning_sent", False)):
            return True
        return str(state.get("event_kind", "") or "").strip() == "last_call"

    def _sanitize_visual_event_snapshot(self, state: Dict[str, Any]) -> Tuple[str, str]:
        event_kind = str(state.get("event_kind", "") or "").strip()
        event_text = str(state.get("event_text", "") or "").strip()
        if event_kind in WORLD_BOSS_QUIET_VISUAL_EVENT_KINDS:
            return "", ""
        return event_kind, event_text

    def _derive_phase_snapshot(self, state: Dict[str, Any]) -> Tuple[str, str]:
        phase = str(state.get("phase", "idle") or "idle").strip()
        if phase == "idle":
            return "idle", ""
        if phase == "recruiting":
            return "entry_open", "ENTRY OPEN"
        if phase == "cooldown":
            last_result = state.get("last_result", {})
            if isinstance(last_result, dict) and last_result:
                if bool(last_result.get("cleared", False)):
                    return "boss_down", "BOSS DOWN"
                return "time_over", "TIME OVER"
            return "cooldown", "COOLDOWN"

        current_hp = max(0, int(state.get("current_hp", 0) or 0))
        max_hp = max(1, int(state.get("max_hp", 1) or 1))
        hp_pct = int(round((current_hp / max_hp) * 100)) if max_hp > 0 else 0
        if hp_pct <= 25:
            return "last_stand", "LAST STAND"
        if hp_pct <= 75:
            return "phase_2", "PHASE 2"
        return "phase_1", "PHASE 1"

    def _derive_event_snapshot(self, state: Dict[str, Any]) -> Tuple[str, str]:
        candidates = [
            *(str(line).strip() for line in reversed(state.get("recent_logs", [])) if str(line).strip()),
        ]

        last_result = state.get("last_result", {})
        if isinstance(last_result, dict) and last_result:
            boss_name = str(last_result.get("boss_name", "WB") or "WB").strip() or "WB"
            if bool(last_result.get("cleared", False)):
                candidates.append(f"討伐成功: {boss_name}")
            else:
                candidates.append(f"時間切れ: {boss_name}")

        phase = str(state.get("phase", "idle") or "idle").strip()
        if phase == "recruiting":
            candidates.append("募集中")
        elif phase == "active":
            candidates.append("戦闘中")

        for raw_line in candidates:
            if not raw_line:
                continue
            if raw_line.startswith("WB全体攻撃:") or "怒りの全体攻撃" in raw_line:
                return "aoe", raw_line
            if raw_line.startswith("戦闘開始:"):
                return "start", raw_line
            if raw_line.startswith("WB激昂"):
                return "enrage", raw_line
            if raw_line.startswith("WB撃破:"):
                return "down", raw_line
            if raw_line.startswith("復帰:"):
                return "recover", raw_line
            if raw_line.startswith("討伐成功:"):
                return "victory", raw_line
            if raw_line.startswith("時間切れ:"):
                return "timeout", raw_line
            if raw_line.startswith("募集開始:") or raw_line == "募集中":
                return "recruiting", raw_line
            if raw_line.startswith("途中参加:"):
                return "late_join", raw_line
            if raw_line.startswith("参加:"):
                return "join", raw_line
            if raw_line.startswith("総合貢献王 "):
                return "ranking", raw_line
            if raw_line.startswith("WB攻撃:"):
                return "attack", raw_line
        return "", ""

    def _refresh_visual_state(self, state: Dict[str, Any]) -> None:
        phase_id, phase_label = self._derive_phase_snapshot(state)
        state["phase_id"] = phase_id
        state["phase_label"] = phase_label

        event_kind = str(state.get("event_kind", "") or "").strip()
        event_text = str(state.get("event_text", "") or "").strip()
        if not event_kind or not event_text:
            event_kind, event_text = self._derive_event_snapshot(state)
        state["event_kind"] = event_kind
        state["event_text"] = event_text
        state["late_join_open"] = str(state.get("phase", "idle") or "idle").strip() in {"recruiting", "active"}

        ranking = self._build_ranking(state.get("participants", {}))
        leader = ranking[0] if ranking else {}
        runner_up = ranking[1] if len(ranking) >= 2 else {}
        leader_name = str(leader.get("display_name", "") or "").strip()
        leader_score = max(
            0,
            int(leader.get("total_contribution_score", leader.get("contribution_score", 0)) or 0),
        )
        runner_up_name = str(runner_up.get("display_name", "") or "").strip()
        runner_up_score = max(
            0,
            int(runner_up.get("total_contribution_score", runner_up.get("contribution_score", 0)) or 0),
        )
        state["leader_name"] = leader_name
        state["leader_score"] = leader_score
        state["runner_up_name"] = runner_up_name
        state["runner_up_score"] = runner_up_score
        state["leader_gap"] = max(0, leader_score - runner_up_score)

    def _set_idle(self, state: Dict[str, Any]) -> None:
        last_result = deepcopy(state.get("last_result", {}))
        pending_announcements = list(state.get("pending_announcements", []))
        state.clear()
        state.update(self._build_idle_state())
        state["last_result"] = last_result
        state["pending_announcements"] = pending_announcements[-WORLD_BOSS_PENDING_ANNOUNCEMENT_LIMIT:]

    def start_boss(
        self,
        boss_id: Optional[str],
        *,
        now: Optional[float] = None,
        auto_spawned: bool = False,
    ) -> Tuple[bool, str]:
        state = self.get_state()
        if state["phase"] in {"recruiting", "active"}:
            boss_name = str(state.get("boss", {}).get("name", "WB") or "WB").strip()
            return False, f"WBはすでに進行中です。 {boss_name}"

        start_at = now_ts() if now is None else float(now)
        if auto_spawned and not str(boss_id or "").strip():
            selected_boss_id, boss = self._pick_random_boss_template()
        else:
            selected_boss_id, boss = self._pick_boss_template(boss_id)
        state.clear()
        state.update(self._build_idle_state())
        state["phase"] = "recruiting"
        state["boss_id"] = selected_boss_id
        state["boss"] = boss
        join_sec = max(1, int(boss.get("join_sec", WORLD_BOSS_JOIN_SEC_DEFAULT)))
        state["join_ends_at"] = start_at + join_sec
        self._push_recent_log(state, f"募集開始: {boss['name']}")
        state["event_kind"] = "recruiting"
        state["event_text"] = f"募集開始: {boss['name']}"
        self._refresh_visual_state(state)
        message = (
            f"WB募集開始 / {boss['name']}"
            f" / {join_sec}秒"
            f" / `!wb参加`"
        )
        if auto_spawned:
            self._queue_announcement(state, message)
        return True, message

    def summon_boss(self, username: str, *, now: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
        safe_username = str(username or "").lower().strip()
        if not safe_username:
            return False, {"reply": "召喚者を判定できませんでした。"}

        state = self.get_state()
        phase = str(state.get("phase", "idle") or "idle").strip()
        if phase != "idle":
            if phase == "cooldown":
                remain = max(0, int(float(state.get("cooldown_ends_at", 0.0) or 0.0) - now_ts()))
                return False, {
                    "reply": f"WBはクールダウン中です。 残り {self.user_service.format_duration(remain)}"
                }
            boss_name = str(state.get("boss", {}).get("name", "WB") or "WB").strip() or "WB"
            return False, {"reply": f"WBはすでに進行中です。 {boss_name}"}

        user = self.user_service.get_user(safe_username)
        inventory = self.user_service.get_material_inventory(user)
        total_materials = sum(max(0, int(amount or 0)) for amount in inventory.values())
        summon_cost = self.get_summon_material_cost()
        if total_materials < summon_cost:
            return False, {
                "reply": (
                    f"WB召喚には強化素材が合計 {summon_cost} 個必要です。 "
                    f"現在 {total_materials}/{summon_cost} / {self._format_summon_material_status(inventory)}"
                )
            }

        spend_plan = self._build_summon_material_spend_plan(inventory, cost=summon_cost)
        if not spend_plan:
            return False, {
                "reply": (
                    f"WB召喚素材の消費計画を組めませんでした。 "
                    f"{self._format_summon_material_status(inventory)}"
                )
            }

        materials = user.setdefault("materials", {})
        spent_labels: List[str] = []
        for slot_name, amount in spend_plan:
            current_amount = max(0, int(materials.get(slot_name, 0) or 0))
            materials[slot_name] = max(0, current_amount - amount)
            spent_labels.append(f"{MATERIAL_LABELS.get(slot_name, slot_name)}x{amount}")

        summon_at = now_ts() if now is None else float(now)
        selected_boss_id, selected_boss = self._pick_random_boss_template()
        ok, headline = self.start_boss(selected_boss_id, now=summon_at)
        if not ok:
            for slot_name, amount in spend_plan:
                materials[slot_name] = max(0, int(materials.get(slot_name, 0) or 0)) + amount
            return False, {"reply": headline}

        display_name = self.user_service.get_display_name(safe_username, safe_username)
        spend_text = " / ".join(spent_labels)
        active_state = self.get_state()
        self._push_recent_log(active_state, f"召喚: {display_name} / {spend_text}")
        return True, {
            "headline": headline,
            "reply": (
                f"{display_name} がWBを召喚。 "
                f"{str(selected_boss.get('name', 'WB') or 'WB').strip() or 'WB'} / "
                f"消費 {spend_text} / `!wb参加`"
            ),
            "cost": summon_cost,
            "spent": spend_text,
            "boss_id": selected_boss_id,
        }

    def _resolve_pending_auto_spawns(self, *, now: float) -> bool:
        progress = self.get_auto_spawn_progress()
        changed = False
        pending_rolls = progress.setdefault("pending_rolls", [])
        while pending_rolls:
            state = self.get_state()
            if state["phase"] != "idle":
                break
            roll = pending_rolls.pop(0)
            changed = True
            failed_rolls = max(0, int(progress.get("failed_rolls", 0) or 0))
            guaranteed = failed_rolls + 1 >= max(1, int(WORLD_BOSS_AUTO_SPAWN_PITY_ROLLS))
            chance = min(1.0, max(0.0, float(roll.get("chance", WORLD_BOSS_AUTO_SPAWN_LEGACY_CHANCE) or 0.0)))
            if not guaranteed and random.random() >= chance:
                progress["failed_rolls"] = failed_rolls + 1
                continue
            started, _ = self.start_boss(None, now=now, auto_spawned=True)
            if started:
                progress["failed_rolls"] = 0
                progress["last_trigger_area"] = str(roll.get("area_name", "") or "").strip()
                progress["last_trigger_chance"] = chance
                self._reset_auto_spawn_pressure(progress)
                return True
        return changed

    def record_area_boss_clear(
        self,
        area_name: Optional[str],
        *,
        now: Optional[float] = None,
    ) -> bool:
        safe_area_name = str(area_name or "").strip()
        if safe_area_name not in AREAS:
            return False

        progress = self.get_auto_spawn_progress()
        current_time = now_ts() if now is None else float(now)
        area_boss_clear_counts = progress.setdefault("area_boss_clear_counts", {})
        clear_count = max(0, int(area_boss_clear_counts.get(safe_area_name, 0) or 0)) + 1
        area_boss_clear_counts[safe_area_name] = clear_count
        progress["claim_count"] = 0
        progress.setdefault("pending_rolls", []).append(
            self._build_pending_auto_spawn_roll(
                safe_area_name,
                boss_clear_count=clear_count,
                triggered_at=current_time,
            )
        )
        progress["completed_cycles"] = max(0, int(progress.get("completed_cycles", 0))) + 1
        progress["last_cycle_completed_at"] = current_time
        self._resolve_pending_auto_spawns(now=current_time)
        return True

    def record_exploration_completion(
        self,
        area_name: Optional[str],
        *,
        now: Optional[float] = None,
    ) -> bool:
        return self.record_area_boss_clear(area_name, now=now)

    def join_boss(self, username: str, *, now: Optional[float] = None) -> Tuple[bool, str]:
        state = self.get_state()
        phase = str(state.get("phase", "idle") or "idle").strip()
        if phase not in {"recruiting", "active"}:
            return False, "WBは現在参加受付中ではありません。"

        safe_username = str(username or "").lower().strip()
        if not safe_username:
            return False, "参加者名を判定できませんでした。"

        user = self.user_service.get_user(safe_username)
        if bool(user.get("down", False)):
            return False, "戦闘不能のためWBに参加できません。 `!蘇生` で復帰してください。"

        participants = state.setdefault("participants", {})
        if safe_username in participants:
            return False, "はすでにWBへ参加登録済みです。"
        join_unlocks = self.user_service.apply_world_boss_join_achievements(user)

        joined_at = now_ts() if now is None else float(now)
        participants[safe_username] = self._build_participant_snapshot(
            safe_username,
            joined_at=joined_at,
            join_phase=phase,
        )
        log_prefix = "参加" if phase == "recruiting" else "途中参加"
        self._push_recent_log(state, f"{log_prefix}: {participants[safe_username]['display_name']}")
        if phase == "active":
            state["late_join_count"] = max(0, int(state.get("late_join_count", 0) or 0)) + 1
            state["event_kind"] = "late_join"
            state["event_text"] = f"途中参加: {participants[safe_username]['display_name']}"
        else:
            state["event_kind"] = "join"
            state["event_text"] = f"参加: {participants[safe_username]['display_name']}"
        self._refresh_visual_state(state)
        count = len(participants)
        join_notes: List[str] = []
        if join_unlocks.get("new_achievements"):
            join_notes.append(f"新実績 {' / '.join(join_unlocks['new_achievements'])}")
        if join_unlocks.get("new_titles"):
            join_notes.append(f"新称号 {' / '.join(join_unlocks['new_titles'])}")
        join_note = f" / {' / '.join(join_notes)}" if join_notes else ""
        if phase == "active":
            return True, f"はWB戦闘に途中参加しました。 現在 {count}人{join_note}"
        return True, f"はWBに参加しました。 現在 {count}人{join_note}"

    def leave_boss(self, username: str) -> Tuple[bool, str]:
        state = self.get_state()
        if state["phase"] != "recruiting":
            return False, "WBの離脱は募集期間中のみ可能です。"

        safe_username = str(username or "").lower().strip()
        participants = state.setdefault("participants", {})
        participant = participants.pop(safe_username, None)
        if not isinstance(participant, dict):
            return False, "はWBへ参加していません。"

        self._push_recent_log(state, f"離脱: {participant.get('display_name', safe_username)}")
        state["event_kind"] = "leave"
        state["event_text"] = f"離脱: {participant.get('display_name', safe_username)}"
        self._refresh_visual_state(state)
        return True, "はWB参加を取り消しました。"

    def _build_ranking(self, participants: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered = sorted(
            participants.values(),
            key=lambda participant: (
                1
                if self._is_owner_rank_content_user(
                    str(participant.get("username", "") or "").strip()
                )
                else 0,
                -int(
                    participant.get(
                        "total_contribution_score",
                        participant.get("contribution_score", 0),
                    )
                    or 0
                ),
                -int(participant.get("total_damage", 0)),
                float(participant.get("joined_at", 0.0)),
                str(participant.get("display_name", "")),
            ),
        )
        ranking: List[Dict[str, Any]] = []
        for index, participant in enumerate(ordered, start=1):
            ranking.append(
                {
                    "rank": index,
                    "username": str(participant.get("username", "") or "").strip(),
                    "display_name": str(participant.get("display_name", "") or "").strip(),
                    "title_label": str(participant.get("title_label", "") or "").strip(),
                    "total_damage": max(0, int(participant.get("total_damage", 0) or 0)),
                    "contribution": deepcopy(
                        self._sanitize_contribution_breakdown(
                            participant.get("contribution", {}),
                            legacy_total=max(0, int(participant.get("contribution_score", 0) or 0)),
                            active_ticks=max(0, int(participant.get("active_ticks", 0) or 0)),
                            total_damage=max(0, int(participant.get("total_damage", 0) or 0)),
                        )
                    ),
                    "total_contribution_score": max(
                        0,
                        int(
                            participant.get(
                                "total_contribution_score",
                                participant.get("contribution_score", 0),
                            )
                            or 0
                        ),
                    ),
                    "contribution_score": max(
                        0,
                        int(
                            participant.get(
                                "total_contribution_score",
                                participant.get("contribution_score", 0),
                            )
                            or 0
                        ),
                    ),
                    "active_ticks": max(0, int(participant.get("active_ticks", 0) or 0)),
                    "times_downed": max(0, int(participant.get("times_downed", 0) or 0)),
                }
            )
        return ranking

    def _begin_battle(self, state: Dict[str, Any], now: float) -> str:
        boss = deepcopy(state.get("boss", {}))
        participants = state.setdefault("participants", {})
        participant_count = max(1, len(participants))
        max_hp = self._scale_boss_hp(int(boss.get("max_hp", 1)), participant_count)

        state["phase"] = "active"
        state["started_at"] = now
        state["ends_at"] = now + max(1, int(boss.get("duration_sec", WORLD_BOSS_DURATION_SEC_DEFAULT)))
        state["last_tick_at"] = now
        state["tick_index"] = 0
        state["current_hp"] = max_hp
        state["max_hp"] = max_hp
        state["boss_action_gauge"] = 0
        state["battle_warning_sent"] = False
        state["aoe_thresholds_triggered"] = []
        state["enrage_announced"] = False
        state["start_participants"] = participant_count
        state["late_join_count"] = 0
        state["late_join_open"] = True

        activated_skills: List[str] = []
        for username, participant in participants.items():
            snapshot = self._sanitize_participant(username, participant)
            snapshot["current_hp"] = snapshot["snapshot_max_hp"]
            snapshot["alive"] = True
            snapshot["respawn_at"] = 0.0
            snapshot["last_damage"] = 0
            snapshot["last_critical"] = False
            snapshot["action_gauge"] = 0
            snapshot["skill_cooldowns"] = {}
            snapshot["active_effects"] = []
            skill_names = [
                str(skill.get("name", "") or "").strip()
                for skill in snapshot.get("active_skills", [])
                if isinstance(skill, dict) and str(skill.get("name", "") or "").strip()
            ]
            if skill_names:
                activated_skills.append(
                    f"{str(snapshot.get('display_name', '?') or '?').strip() or '?'}:{'/'.join(skill_names[:2])}"
                )
            participants[username] = snapshot

        self._push_recent_log(state, f"戦闘開始: {boss.get('name', 'WB')} / HP {max_hp}")
        if activated_skills:
            self._push_recent_log(state, f"スキル発動: {' / '.join(activated_skills[:3])}")
        state["event_kind"] = "start"
        state["event_text"] = f"戦闘開始: {boss.get('name', 'WB')} / HP {max_hp}"
        self._refresh_visual_state(state)
        return (
            f"WB開始 / {boss.get('name', 'WB')}"
            f" / HP {max_hp}"
            f" / {participant_count}人参加"
        )

    def skip_recruiting(self, *, now: Optional[float] = None) -> Tuple[bool, str]:
        state = self.get_state()
        if state["phase"] != "recruiting":
            return False, "WBは募集状態ではありません。"

        if not state.get("participants"):
            return False, "WB参加者がいないため開始できません。"

        started_at = now_ts() if now is None else float(now)
        return True, self._begin_battle(state, started_at)

    def stop_boss(self) -> Tuple[bool, str]:
        state = self.get_state()
        if state["phase"] not in {"recruiting", "active", "cooldown"}:
            return False, "停止できるWBイベントがありません。"
        boss_name = str(state.get("boss", {}).get("name", "WB") or "WB").strip()
        self._set_idle(state)
        return True, f"WBを停止しました。 {boss_name}"

    def _apply_damage_to_participant(
        self,
        participant: Dict[str, Any],
        *,
        damage: int,
        now: float,
        respawn_sec: int,
    ) -> bool:
        participant["current_hp"] = max(0, int(participant.get("current_hp", 0)) - max(1, int(damage)))
        if participant["current_hp"] > 0:
            return False
        participant["alive"] = False
        participant["action_gauge"] = 0
        participant["respawn_at"] = now + max(1, int(respawn_sec))
        participant["times_downed"] = max(0, int(participant.get("times_downed", 0))) + 1
        return True

    def _handle_respawns(self, state: Dict[str, Any], *, now: float) -> None:
        boss = state.get("boss", {})
        try:
            respawn_hp_ratio = float(boss.get("respawn_hp_ratio", 1.0) or 1.0)
        except (TypeError, ValueError):
            respawn_hp_ratio = 1.0
        if respawn_hp_ratio <= 0.0 or respawn_hp_ratio > 1.0:
            respawn_hp_ratio = 1.0
        respawned_names: List[str] = []
        for participant in state.get("participants", {}).values():
            if not isinstance(participant, dict):
                continue
            if bool(participant.get("alive", False)):
                continue
            respawn_at = float(participant.get("respawn_at", 0.0) or 0.0)
            if respawn_at <= 0.0 or now < respawn_at:
                continue
            participant["alive"] = True
            participant["respawn_at"] = 0.0
            snapshot_max_hp = max(1, int(participant.get("snapshot_max_hp", 1)))
            participant["current_hp"] = max(
                1,
                int(snapshot_max_hp * respawn_hp_ratio),
            )
            participant["action_gauge"] = 0
            respawned_names.append(str(participant.get("display_name", "?") or "?").strip() or "?")

        if respawned_names:
            recover_text = f"復帰: {' / '.join(respawned_names[:3])}"
            self._push_recent_log(state, recover_text)
            state["event_kind"] = "recover"
            state["event_text"] = recover_text
            self._refresh_visual_state(state)

    def _get_alive_participants(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            participant
            for participant in state.get("participants", {}).values()
            if isinstance(participant, dict) and bool(participant.get("alive", False))
        ]

    def _get_participant_stats(self, participant: Dict[str, Any]) -> Dict[str, int]:
        unit = {
            "base_stats": normalize_stats(
                participant.get(
                    "snapshot_stats",
                    {
                        "atk": participant.get("snapshot_atk", 1),
                        "def": participant.get("snapshot_def", 0),
                        "speed": participant.get("snapshot_speed", 100),
                        "max_hp": participant.get("snapshot_max_hp", 1),
                    },
                )
            ),
            "active_effects": participant.get("active_effects", []),
        }
        return self.battle_service.get_unit_stats(unit)

    def _run_player_phase(self, state: Dict[str, Any]) -> None:
        alive_participants = self._get_alive_participants(state)
        if not alive_participants:
            self._push_recent_log(state, "攻撃参加者なし")
            return

        boss = state.get("boss", {})
        boss_def = max(0, int(boss.get("def", 0)))
        total_damage = 0
        critical_count = 0
        action_count = 0
        activated_skills: List[str] = []

        self.battle_service.advance_action_gauges(alive_participants)
        ready_participants = self.battle_service.get_ready_units(alive_participants)
        while ready_participants:
            participant = ready_participants[0]
            participant_stats = self._get_participant_stats(participant)
            selected_skill = self.battle_service.select_auto_skill(participant)
            skill_effect = self.battle_service.create_skill_effect(selected_skill) if selected_skill else None
            skill_deals_damage = self.battle_service.skill_deals_damage(selected_skill)
            skill_action_gauge_bonus = self.battle_service.get_skill_action_gauge_bonus(selected_skill)
            if skill_effect and self.battle_service.skill_has_special_effect(selected_skill, "action_gauge_regen"):
                skill_action_gauge_bonus = 0
            if selected_skill and skill_effect:
                support_score = self._estimate_support_score_from_skill(selected_skill)
                activated_skills.append(
                    f"{str(participant.get('display_name', '?') or '?').strip() or '?'}:{selected_skill.get('name', 'スキル')}"
                )
                participant["last_damage"] = 0
                participant["last_critical"] = False
                participant["active_ticks"] = max(0, int(participant.get("active_ticks", 0))) + 1
                self._add_participant_contribution(participant, support=support_score, survival=1)
                self.battle_service.finalize_unit_action(
                    participant,
                    used_skill=selected_skill,
                    new_effect=skill_effect,
                    action_gauge_bonus=skill_action_gauge_bonus,
                )
                action_count += 1
                ready_participants = self.battle_service.get_ready_units(alive_participants)
                continue
            if selected_skill and not skill_deals_damage:
                support_score = self._estimate_support_score_from_skill(selected_skill)
                activated_skills.append(
                    f"{str(participant.get('display_name', '?') or '?').strip() or '?'}:{selected_skill.get('name', 'スキル')}"
                )
                participant["last_damage"] = 0
                participant["last_critical"] = False
                participant["active_ticks"] = max(0, int(participant.get("active_ticks", 0))) + 1
                self._add_participant_contribution(participant, support=support_score, survival=1)
                self.battle_service.finalize_unit_action(
                    participant,
                    used_skill=selected_skill,
                    action_gauge_bonus=skill_action_gauge_bonus,
                )
                action_count += 1
                ready_participants = self.battle_service.get_ready_units(alive_participants)
                continue

            action_stats = self.battle_service.get_unit_stats(
                {
                    "base_stats": participant_stats,
                    "active_effects": (
                        [
                            {
                                "stats": selected_skill.get("stats", {}),
                                "actions_left": 1,
                            }
                        ]
                        if selected_skill and not skill_effect
                        else []
                    ),
                }
            )
            effective_boss_def = self.battle_service.get_effective_defense(
                boss_def,
                selected_skill,
            )
            damage, is_critical = self.battle_service.roll_attack_damage(
                int(action_stats.get("atk", 1)),
                effective_boss_def,
                crit_chance=float(participant.get("snapshot_crit_rate", 0.0)),
                crit_damage_multiplier=float(participant.get("snapshot_crit_damage_multiplier", 1.0)),
            )
            if selected_skill and not skill_effect:
                damage = self.battle_service.scale_damage_for_skill(damage, selected_skill)
            participant["last_damage"] = max(1, int(damage))
            participant["last_critical"] = bool(is_critical)
            participant["total_damage"] = max(0, int(participant.get("total_damage", 0))) + max(1, int(damage))
            participant["active_ticks"] = max(0, int(participant.get("active_ticks", 0))) + 1
            self._add_participant_contribution(
                participant,
                damage=max(1, int(damage)),
                survival=1,
            )
            total_damage += max(1, int(damage))
            if is_critical:
                critical_count += 1
            self.battle_service.finalize_unit_action(
                participant,
                used_skill=selected_skill,
                action_gauge_bonus=skill_action_gauge_bonus,
            )
            action_count += 1
            ready_participants = self.battle_service.get_ready_units(alive_participants)

        state["current_hp"] = max(0, int(state.get("current_hp", 0)) - total_damage)
        if activated_skills:
            self._push_recent_log(
                state,
                f"スキル発動: {' / '.join(activated_skills[:3])}",
            )
        if action_count <= 0:
            self._push_recent_log(state, "攻撃参加者なし")
            return
        if critical_count > 0:
            self._push_recent_log(
                state,
                f"T{int(state.get('tick_index', 0))}: {action_count}行動で{total_damage}ダメ / 会心{critical_count}",
            )
        else:
            self._push_recent_log(
                state,
                f"T{int(state.get('tick_index', 0))}: {action_count}行動で{total_damage}ダメ",
            )
        self._refresh_visual_state(state)

    def _run_threshold_aoe(self, state: Dict[str, Any], *, threshold: int, now: float) -> str:
        boss = state.get("boss", {})
        respawn_sec = max(1, int(boss.get("respawn_sec", 12)))
        downed_count = 0
        hit_count = 0
        downed_names: List[str] = []
        for participant in self._get_alive_participants(state):
            participant_stats = self._get_participant_stats(participant)
            participant_damage = self.battle_service.get_base_damage(
                int(boss.get("atk", 1)),
                int(participant_stats.get("def", 0)),
            )
            hit_count += 1
            if self._apply_damage_to_participant(
                participant,
                damage=participant_damage,
                now=now,
                respawn_sec=respawn_sec,
            ):
                downed_count += 1
                downed_names.append(str(participant.get("display_name", "?") or "?").strip() or "?")
        log_line = f"WB全体攻撃: {hit_count}人へ / 戦闘不能{downed_count}人"
        if downed_names:
            preview_names = downed_names[:3]
            log_line += f" / {' / '.join(preview_names)}"
            omitted_count = max(0, len(downed_names) - len(preview_names))
            if omitted_count > 0:
                log_line += f" / ...ほか{omitted_count}人"
        self._push_recent_log(
            state,
            log_line,
        )
        if threshold in WORLD_BOSS_MAJOR_PHASE_THRESHOLDS:
            phase_id, phase_label = WORLD_BOSS_MAJOR_PHASE_THRESHOLDS[threshold]
            state["phase_id"] = phase_id
            state["phase_label"] = phase_label
            state["event_kind"] = "aoe"
            state["event_text"] = log_line
            self._refresh_visual_state(state)
            return f"WB HP{threshold}%突破 / {phase_label}"
        state["event_kind"] = "aoe"
        state["event_text"] = log_line
        self._refresh_visual_state(state)
        return ""

    def _run_single_target_attack(self, state: Dict[str, Any], *, now: float, enraged: bool) -> None:
        boss = state.get("boss", {})
        alive_participants = self._get_alive_participants(state)
        if not alive_participants:
            return

        target = random.choice(alive_participants)
        bonus = max(0, int(boss.get("enrage_atk_bonus", 0))) if enraged else 0
        respawn_sec = max(1, int(boss.get("respawn_sec", 12)))
        target_stats = self._get_participant_stats(target)
        damage = self.battle_service.get_base_damage(
            int(boss.get("atk", 1)) + bonus,
            int(target_stats.get("def", 0)),
        )
        downed = self._apply_damage_to_participant(
            target,
            damage=damage,
            now=now,
            respawn_sec=respawn_sec,
        )
        target_name = str(target.get("display_name", "?") or "?").strip() or "?"
        if downed:
            self._push_recent_log(
                state,
                f"WB撃破: {target_name} / {damage}ダメ / 復帰{respawn_sec}秒",
            )
            state["event_kind"] = "down"
            state["event_text"] = f"WB撃破: {target_name} / {damage}ダメ / 復帰{respawn_sec}秒"
            self._refresh_visual_state(state)
            return
        self._push_recent_log(
            state,
            f"WB攻撃: {target_name} に {damage}ダメ",
        )
        state["event_kind"] = "attack"
        state["event_text"] = f"WB攻撃: {target_name} に {damage}ダメ"
        self._refresh_visual_state(state)

    def _run_boss_phase(self, state: Dict[str, Any], *, now: float) -> List[str]:
        boss = state.get("boss", {})
        messages: List[str] = []
        if int(state.get("current_hp", 0)) <= 0:
            return messages

        hp_pct = (int(state.get("current_hp", 0)) / max(1, int(state.get("max_hp", 1)))) * 100.0
        triggered = state.setdefault("aoe_thresholds_triggered", [])
        for threshold in boss.get("aoe_thresholds", []):
            safe_threshold = int(threshold)
            if safe_threshold in triggered:
                continue
            if hp_pct > safe_threshold:
                continue
            triggered.append(safe_threshold)
            threshold_message = self._run_threshold_aoe(state, threshold=safe_threshold, now=now)
            if threshold_message:
                messages.append(threshold_message)
            return messages

        enrage_threshold_pct = max(1, int(boss.get("enrage_threshold_pct", 20)))
        enraged = hp_pct <= enrage_threshold_pct
        if enraged and not bool(state.get("enrage_announced", False)):
            state["enrage_announced"] = True
            state["event_kind"] = "enrage"
            state["event_text"] = f"WB激昂 / {boss.get('name', 'WB')} の攻撃が激化"
            self._refresh_visual_state(state)

        self._run_single_target_attack(state, now=now, enraged=enraged)
        return messages

    def _update_user_records(
        self,
        user: Dict[str, Any],
        *,
        cleared: bool,
        rank: int,
        total_damage: int,
    ) -> None:
        records = user.setdefault("world_boss_records", {})
        records["entries"] = max(0, int(records.get("entries", 0))) + 1
        if cleared:
            records["clears"] = max(0, int(records.get("clears", 0))) + 1
        if rank == 1:
            records["mvp_count"] = max(0, int(records.get("mvp_count", 0))) + 1
        best_rank = max(0, int(records.get("best_rank", 0)))
        if best_rank <= 0 or rank < best_rank:
            records["best_rank"] = rank
        if total_damage > max(0, int(records.get("best_damage", 0))):
            records["best_damage"] = total_damage

    def _grant_participant_rewards(
        self,
        *,
        user: Dict[str, Any],
        boss: Dict[str, Any],
        participant: Dict[str, Any],
        rank: int,
        participant_count: int,
        cleared: bool,
    ) -> Dict[str, Any]:
        self._ensure_user_world_boss_data(user)
        total_damage = max(0, int(participant.get("total_damage", 0)))
        eligible = self._is_participant_reward_eligible(boss, participant)

        exp_reward = 0
        gold_reward = 0
        material_reward = 0
        if eligible:
            exp_reward = max(0, int(boss.get("participation_exp", 0)))
            gold_reward = max(0, int(boss.get("participation_gold", 0)))
            material_reward = max(0, int(boss.get("participation_material", 0)))
            if cleared:
                exp_reward += max(0, int(boss.get("clear_exp_bonus", 0)))
                gold_reward += max(0, int(boss.get("clear_gold_bonus", 0)))
                material_reward += max(0, int(boss.get("clear_material_bonus", 0)))
            else:
                reward_rate = min(1.0, max(0.0, float(boss.get("failure_reward_rate", 0.5))))
                exp_reward = int(round(exp_reward * reward_rate))
                gold_reward = int(round(gold_reward * reward_rate))
                material_reward = int(round(material_reward * reward_rate))

            bonus_rate = 0.0
            if rank == 1:
                bonus_rate = float(boss.get("mvp_bonus_rate", 0.5))
            elif rank == 2:
                bonus_rate = float(boss.get("runner_up_bonus_rate", 0.25))
            elif rank == 3:
                bonus_rate = float(boss.get("third_bonus_rate", 0.1))
            if bonus_rate > 0.0:
                exp_reward = int(round(exp_reward * (1.0 + bonus_rate)))
                gold_reward = int(round(gold_reward * (1.0 + bonus_rate)))
                material_reward = int(round(material_reward * (1.0 + bonus_rate)))

        if exp_reward > 0:
            user["adventure_exp"] = max(0, int(user.get("adventure_exp", 0))) + exp_reward
        if gold_reward > 0:
            user["gold"] = max(0, int(user.get("gold", 0))) + gold_reward
        if material_reward > 0:
            material_key = str(boss.get("material_key", "") or "").strip()
            materials = user.setdefault("world_boss_materials", {})
            materials[material_key] = max(0, int(materials.get(material_key, 0))) + material_reward
        self.user_service.sync_level_stats(user)
        self._update_user_records(
            user,
            cleared=cleared and eligible,
            rank=rank,
            total_damage=total_damage,
        )

        return {
            "eligible": eligible,
            "exp": max(0, exp_reward),
            "gold": max(0, gold_reward),
            "material_key": str(boss.get("material_key", "") or "").strip(),
            "material_label": str(boss.get("material_label", "") or "").strip(),
            "material_amount": max(0, material_reward),
            "participant_count": max(1, participant_count),
        }

    def _build_user_result(
        self,
        *,
        boss: Dict[str, Any],
        participant: Dict[str, Any],
        rewards: Dict[str, Any],
        rank: int,
        cleared: bool,
        ended_at: float,
    ) -> Dict[str, Any]:
        return {
            "boss_id": str(boss.get("boss_id", "") or "").strip(),
            "boss_name": str(boss.get("name", "WB") or "WB").strip() or "WB",
            "boss_title": str(boss.get("title", "") or "").strip(),
            "title_label": str(participant.get("title_label", "") or "").strip(),
            "cleared": bool(cleared),
            "rank": max(1, int(rank)),
            "participant_count": max(1, int(rewards.get("participant_count", 1))),
            "total_damage": max(0, int(participant.get("total_damage", 0))),
            "contribution": deepcopy(
                self._sanitize_contribution_breakdown(
                    participant.get("contribution", {}),
                    legacy_total=max(0, int(participant.get("contribution_score", 0) or 0)),
                    active_ticks=max(0, int(participant.get("active_ticks", 0) or 0)),
                    total_damage=max(0, int(participant.get("total_damage", 0) or 0)),
                )
            ),
            "total_contribution_score": max(
                0,
                int(
                    participant.get(
                        "total_contribution_score",
                        participant.get("contribution_score", 0),
                    )
                    or 0
                ),
            ),
            "contribution_score": max(0, int(participant.get("contribution_score", 0))),
            "active_ticks": max(0, int(participant.get("active_ticks", 0))),
            "times_downed": max(0, int(participant.get("times_downed", 0))),
            "eligible": bool(rewards.get("eligible", False)),
            "rewards": {
                "exp": max(0, int(rewards.get("exp", 0))),
                "gold": max(0, int(rewards.get("gold", 0))),
                "material_key": str(rewards.get("material_key", "") or "").strip(),
                "material_label": str(rewards.get("material_label", "") or "").strip(),
                "material_amount": max(0, int(rewards.get("material_amount", 0))),
            },
            "ended_at": float(ended_at),
        }

    def _append_user_history(self, user: Dict[str, Any], result: Dict[str, Any]) -> None:
        history = user.setdefault("world_boss_history", [])
        history.insert(0, deepcopy(result))
        del history[WORLD_BOSS_HISTORY_LIMIT:]

    def _resolve_battle(self, state: Dict[str, Any], *, now: float, cleared: bool) -> List[str]:
        boss = deepcopy(state.get("boss", {}))
        participants = state.get("participants", {})
        objective_score_bonus = self._get_objective_score_bonus(boss, cleared=cleared)
        if objective_score_bonus > 0:
            for participant in participants.values():
                if not isinstance(participant, dict):
                    continue
                if not self._is_participant_reward_eligible(boss, participant):
                    continue
                self._add_participant_contribution(participant, objective=objective_score_bonus)
        ranking = self._build_ranking(participants)
        participant_count = len(ranking)
        total_damage = sum(int(entry.get("total_damage", 0)) for entry in ranking)
        achievement_announcements: List[str] = []

        for entry in ranking:
            username = str(entry.get("username", "") or "").strip()
            if not username:
                continue
            participant = participants.get(username, {})
            user = self.user_service.get_user(username)
            rewards = self._grant_participant_rewards(
                user=user,
                boss=boss,
                participant=participant,
                rank=int(entry.get("rank", 1)),
                participant_count=participant_count,
                cleared=cleared,
            )
            result = self._build_user_result(
                boss=boss,
                participant=participant,
                rewards=rewards,
                rank=int(entry.get("rank", 1)),
                cleared=cleared,
                ended_at=now,
            )
            achievement_unlocks = self.user_service.apply_world_boss_result_achievements(user, result)
            result["new_achievements"] = list(achievement_unlocks.get("new_achievements", []))
            result["new_titles"] = list(achievement_unlocks.get("new_titles", []))
            updated_title_label = self.user_service.get_active_title_label(user)
            result["title_label"] = updated_title_label
            participant["title_label"] = updated_title_label
            entry["title_label"] = updated_title_label
            if "wb_mvp" in achievement_unlocks.get("new_achievement_ids", []) and result["new_titles"]:
                achievement_announcements.append(
                    f"新称号 {entry.get('display_name', '?')} / {result['new_titles'][0]}"
                )
            user["last_world_boss_result"] = deepcopy(result)
            self._append_user_history(user, result)

        state["ranking"] = ranking[:10]
        state["last_result"] = {
            "boss_id": str(boss.get("boss_id", "") or "").strip(),
            "boss_name": str(boss.get("name", "WB") or "WB").strip() or "WB",
            "boss_title": str(boss.get("title", "") or "").strip(),
            "cleared": bool(cleared),
            "ended_at": float(now),
            "participant_count": participant_count,
            "total_damage": total_damage,
            "ranking": deepcopy(ranking[:10]),
        }
        state["phase"] = "cooldown"
        state["cooldown_ends_at"] = now + WORLD_BOSS_COOLDOWN_SEC
        state["late_join_open"] = False
        self._push_recent_log(
            state,
            f"{'討伐成功' if cleared else '時間切れ'}: {boss.get('name', 'WB')}",
        )

        top_entry = ranking[0] if ranking else {}
        top_name = str(top_entry.get("display_name", "") or "").strip()
        top_damage = max(0, int(top_entry.get("total_damage", 0)))
        top_score = max(
            0,
            int(top_entry.get("total_contribution_score", top_entry.get("contribution_score", 0)) or 0),
        )
        state["event_kind"] = "victory" if cleared else "timeout"
        state["event_text"] = f"{'討伐成功' if cleared else '時間切れ'}: {boss.get('name', 'WB')}"
        self._refresh_visual_state(state)
        if cleared:
            if top_name:
                messages = [
                    f"WB討伐成功 / {boss.get('name', 'WB')}",
                    f"総合貢献王 {top_name} / 貢献 {top_score} / {top_damage}ダメ",
                ]
                messages.extend(achievement_announcements[:1])
                return messages
            messages = [f"WB討伐成功 / {boss.get('name', 'WB')}"]
            messages.extend(achievement_announcements[:1])
            return messages
        if top_name:
            messages = [
                f"WB時間切れ / {boss.get('name', 'WB')}",
                f"総合貢献王 {top_name} / 貢献 {top_score} / {top_damage}ダメ",
            ]
            messages.extend(achievement_announcements[:1])
            return messages
        messages = [f"WB時間切れ / {boss.get('name', 'WB')}"]
        messages.extend(achievement_announcements[:1])
        return messages

    def _run_tick(self, state: Dict[str, Any], *, now: float) -> List[str]:
        state["last_tick_at"] = float(now)
        state["tick_index"] = max(0, int(state.get("tick_index", 0))) + 1
        self._handle_respawns(state, now=now)
        self._run_player_phase(state)
        if int(state.get("current_hp", 0)) <= 0:
            return self._resolve_battle(state, now=now, cleared=True)

        messages: List[str] = []
        boss = state.get("boss", {})
        boss_speed = int(boss.get("speed", 0) or 0)
        if boss_speed <= 0:
            attack_interval = max(1, int(boss.get("boss_attack_every_ticks", 2)))
            boss_speed = max(1, int(round(GAUGE_THRESHOLD / attack_interval)))
        state["boss_action_gauge"] = max(0, int(state.get("boss_action_gauge", 0) or 0)) + boss_speed
        while int(state.get("boss_action_gauge", 0)) >= GAUGE_THRESHOLD and state["phase"] == "active":
            state["boss_action_gauge"] = max(0, int(state.get("boss_action_gauge", 0)) - GAUGE_THRESHOLD)
            messages.extend(self._run_boss_phase(state, now=now))
            if int(state.get("current_hp", 0)) <= 0:
                break
        return messages

    def process(self, *, now: Optional[float] = None) -> Tuple[List[str], bool]:
        state = self.get_state()
        current_time = now_ts() if now is None else float(now)
        messages = self._drain_announcements(state)
        changed = bool(messages)

        if state["phase"] == "recruiting":
            if (
                not bool(state.get("join_warning_sent", False))
                and float(state.get("join_ends_at", 0.0)) - current_time <= 10.0
            ):
                state["join_warning_sent"] = True
                state["event_kind"] = "recruiting"
                state["event_text"] = "開始まで残り10秒"
                self._refresh_visual_state(state)
                messages.append("WB開始まで残り10秒 / `!wb参加`")
                changed = True
            if current_time >= float(state.get("join_ends_at", 0.0)):
                if not state.get("participants"):
                    boss_name = str(state.get("boss", {}).get("name", "WB") or "WB").strip() or "WB"
                    self._set_idle(state)
                    messages.append(f"WB中止 / 参加者なし / {boss_name}")
                else:
                    messages.append(self._begin_battle(state, current_time))
                changed = True
            return messages, changed

        if state["phase"] == "active":
            if (
                not bool(state.get("battle_warning_sent", False))
                and float(state.get("ends_at", 0.0)) - current_time <= 30.0
            ):
                state["battle_warning_sent"] = True
                state["event_kind"] = "last_call"
                state["event_text"] = "WB残り30秒"
                self._refresh_visual_state(state)
                messages.append("WB残り30秒")
                changed = True

            tick_sec = max(1, int(state.get("boss", {}).get("tick_sec", 2)))
            safety_count = 0
            while (
                state["phase"] == "active"
                and current_time >= float(state.get("last_tick_at", 0.0)) + tick_sec
                and safety_count < 10
            ):
                safety_count += 1
                tick_messages = self._run_tick(
                    state,
                    now=float(state.get("last_tick_at", 0.0)) + tick_sec,
                )
                if tick_messages:
                    messages.extend(tick_messages)
                changed = True

            if state["phase"] == "active" and current_time >= float(state.get("ends_at", 0.0)):
                messages.extend(self._resolve_battle(state, now=current_time, cleared=False))
                changed = True
            return messages, changed

        if state["phase"] == "cooldown" and current_time >= float(state.get("cooldown_ends_at", 0.0)):
            self._set_idle(state)
            changed = True

        if state["phase"] == "idle":
            if self._resolve_pending_auto_spawns(now=current_time):
                changed = True
                state = self.get_state()
                messages.extend(self._drain_announcements(state))
            return messages, changed

        return messages, changed

    def get_status(self, username: Optional[str] = None) -> Dict[str, Any]:
        state = self.get_state()
        participants = state.get("participants", {})
        ranking = (
            self._build_ranking(participants)
            if state["phase"] in {"recruiting", "active"}
            else list(state.get("ranking", []))
        )

        safe_username = str(username or "").lower().strip()
        participant = participants.get(safe_username) if safe_username else None
        participant_entry = None
        if isinstance(participant, dict):
            participant_entry = self._sanitize_participant(safe_username, participant)
            participant_entry["current_stats"] = self._get_participant_stats(participant_entry)
            for entry in ranking:
                if str(entry.get("username", "") or "").strip() == safe_username:
                    participant_entry["rank"] = int(entry.get("rank", 0))
                    break
        event_kind, event_text = self._sanitize_visual_event_snapshot(state)
        race_focus_active = self._should_highlight_race(state)

        return {
            "phase": str(state.get("phase", "idle") or "idle"),
            "phase_id": str(state.get("phase_id", "") or "").strip(),
            "phase_label": str(state.get("phase_label", "") or "").strip(),
            "event_kind": event_kind,
            "event_text": event_text,
            "boss_id": str(state.get("boss_id", "") or "").strip(),
            "boss": deepcopy(state.get("boss", {})),
            "current_hp": max(0, int(state.get("current_hp", 0) or 0)),
            "max_hp": max(0, int(state.get("max_hp", 0) or 0)),
            "join_ends_at": float(state.get("join_ends_at", 0.0) or 0.0),
            "started_at": float(state.get("started_at", 0.0) or 0.0),
            "ends_at": float(state.get("ends_at", 0.0) or 0.0),
            "cooldown_ends_at": float(state.get("cooldown_ends_at", 0.0) or 0.0),
            "start_participants": max(0, int(state.get("start_participants", 0) or 0)),
            "late_join_count": max(0, int(state.get("late_join_count", 0) or 0)),
            "late_join_open": bool(state.get("late_join_open", False)),
            "leader_name": str(state.get("leader_name", "") or "").strip(),
            "leader_score": max(0, int(state.get("leader_score", 0) or 0)),
            "runner_up_name": str(state.get("runner_up_name", "") or "").strip(),
            "runner_up_score": max(0, int(state.get("runner_up_score", 0) or 0)),
            "leader_gap": max(0, int(state.get("leader_gap", 0) or 0)),
            "race_focus_active": race_focus_active,
            "participants": len(participants),
            "ranking": deepcopy(ranking[:5]),
            "recent_logs": list(state.get("recent_logs", [])),
            "self": participant_entry,
            "last_result": deepcopy(state.get("last_result", {})),
        }

    def get_user_last_result(self, username: str) -> Optional[Dict[str, Any]]:
        safe_username = str(username or "").lower().strip()
        if not safe_username:
            return None
        user = self.user_service.get_user(safe_username)
        self._ensure_user_world_boss_data(user)
        last_result = user.get("last_world_boss_result")
        return deepcopy(last_result) if isinstance(last_result, dict) else None
