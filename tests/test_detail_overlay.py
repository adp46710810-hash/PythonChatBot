from __future__ import annotations

import unittest
from pathlib import Path

from rpg_core.detail_overlay import DetailOverlayWriter


class DetailOverlayWriterTests(unittest.TestCase):
    def test_shell_html_uses_iframe_swapper_instead_of_meta_refresh(self) -> None:
        writer = DetailOverlayWriter("data/runtime/obs_detail_overlay.html", "unused.txt")

        shell_payload = writer._render_shell_html("Alice / !wb")

        self.assertIn("overlay-frame-a", shell_payload)
        self.assertIn("overlay-frame-b", shell_payload)
        self.assertIn("obs_detail_overlay_content.html", shell_payload)
        self.assertIn("setInterval(swapFrame, 2000)", shell_payload)
        self.assertNotIn("http-equiv=\"refresh\"", shell_payload)

    def test_split_shell_html_uses_variant_content_paths(self) -> None:
        writer = DetailOverlayWriter("data/runtime/obs_detail_overlay.html", "unused.txt")

        info_shell_payload = writer._render_shell_html("Alice / !wb", variant="info")
        wb_shell_payload = writer._render_shell_html("Alice / !wb", variant="wb")

        self.assertIn("obs_detail_overlay_info_content.html", info_shell_payload)
        self.assertIn("obs_detail_overlay_wb_state.js", wb_shell_payload)
        self.assertIn("obs_detail_overlay_info_content.html", wb_shell_payload)
        self.assertIn("wb-info-frame-a", wb_shell_payload)
        self.assertIn("wb-stage-art", wb_shell_payload)
        self.assertIn("payload.stageClasses", wb_shell_payload)
        self.assertIn("payload.eventClasses", wb_shell_payload)
        self.assertIn("payload.rankingChipText", wb_shell_payload)
        self.assertIn("payload.timeCritical", wb_shell_payload)
        self.assertIn("payload.presentationTrigger", wb_shell_payload)
        self.assertIn("payload.presentationTone", wb_shell_payload)

    def test_wb_shell_html_detects_hp_drop_and_restarts_hit_effect(self) -> None:
        writer = DetailOverlayWriter("data/runtime/obs_detail_overlay.html", "unused.txt")

        wb_shell_payload = writer._render_shell_html("Alice / !wb", variant="wb")

        self.assertIn("const previousState = lastState;", wb_shell_payload)
        self.assertIn("const detectBossHit = (previousPayload, nextPayload) => {", wb_shell_payload)
        self.assertIn('restartStageEffect("wb-stage--boss-hit")', wb_shell_payload)
        self.assertIn('let pendingVisualUrl = "";', wb_shell_payload)
        self.assertIn('const hadVisibleArt = Boolean(currentVisualUrl && art.getAttribute("src"));', wb_shell_payload)
        self.assertIn(".wb-stage--boss-hit .wb-stage__aura", wb_shell_payload)
        self.assertIn(".wb-stage--boss-hit .wb-stage__impact", wb_shell_payload)
        self.assertNotIn(".wb-stage.wb-theme--fencer.wb-stage--boss-hit", wb_shell_payload)
        self.assertIn("@keyframes wb-boss-hit-shudder", wb_shell_payload)

    def test_structured_overlay_lines_render_clean_text_and_html(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: 次の一手",
                    "kv: 要約 | 朝の森へ向かう",
                    "meta: wb_phase | active",
                    "alert: kv: 状態 | 戦闘不能",
                    "通常行も残す",
                ]
            )
        )
        text_payload = writer._render_text("Test Overlay", "2026-03-19 12:00:00", entries)
        html_payload = writer._render_html("Test Overlay", "2026-03-19 12:00:00", entries)

        self.assertIn("[次の一手]", text_payload)
        self.assertIn("要約: 朝の森へ向かう", text_payload)
        self.assertIn("! 状態: 戦闘不能", text_payload)
        self.assertIn("通常行も残す", text_payload)
        self.assertNotIn("wb_phase", text_payload)

        self.assertIn('class="section"', html_payload)
        self.assertIn('class="line line--kv"', html_payload)
        self.assertIn('class="line line--kv line--alert"', html_payload)
        self.assertIn("通常行も残す", html_payload)
        self.assertNotIn("wb_phase", html_payload)

    def test_world_boss_overlay_renders_visual_panel_and_motion_classes(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                    "kv: 状態 | 戦闘中 / 残り 22秒",
                    "kv: 参加人数 | 3人",
                    "kv: HP | 480/1500 (32%)",
                    "section: 直近ログ",
                    "kv: 1 | 戦闘開始: 灼甲帝ヴァルカラン / HP 1500",
                    "kv: 2 | WB激昂 / 灼甲帝ヴァルカラン",
                    "kv: 3 | WB全体攻撃: Alice に 34ダメ",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-24 12:00:00", entries)

        self.assertIn('class="wb-layout"', html_payload)
        self.assertIn("灼甲帝ヴァルカラン", html_payload)
        self.assertIn("紅蓮を喰らう甲殻王", html_payload)
        self.assertIn("wb-stage--active", html_payload)
        self.assertIn("wb-stage--attack", html_payload)
        self.assertIn("wb-stage--phase-3", html_payload)
        self.assertIn("wb-stage--aoe", html_payload)
        self.assertIn("wb-theme--crimson", html_payload)
        self.assertIn("wb-stage__hp-fill", html_payload)
        self.assertIn("wb-stage__motion", html_payload)
        self.assertIn("wb-stage__pose", html_payload)
        self.assertIn("wb-stage__shadow", html_payload)
        self.assertIn("wb-stage__impact", html_payload)
        self.assertIn("wb-stage__phase", html_payload)
        self.assertIn("PHASE 3", html_payload)
        self.assertIn("wb-stage__event--aoe", html_payload)
        self.assertIn("WB全体攻撃: Alice に 34ダメ", html_payload)

    def test_world_boss_idle_overlay_does_not_render_stage_panel(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: コマンド | !wb",
                    "kv: ユーザー | Alice",
                    "kv: 状態 | 待機中",
                    "kv: 前回 | 灼甲帝ヴァルカラン / 討伐済み",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-24 12:00:00", entries)

        self.assertIn('class="wb-layout wb-layout--compact"', html_payload)
        self.assertIn('class="overlay overlay--wb overlay--wb-full"', html_payload)
        self.assertNotIn('class="wb-stage', html_payload)

    def test_world_boss_result_overlay_does_not_render_stage_panel(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: WB結果",
                    "kv: コマンド | !wb結果",
                    "kv: ユーザー | Alice",
                    "kv: 結果 | 灼甲帝ヴァルカラン / 討伐成功",
                    "kv: 戦果 | 順位 #1 / 520ダメ / 貢献 750 / 離脱 0回",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb結果", "2026-03-24 12:00:00", entries)

        self.assertIn('class="wb-layout wb-layout--compact"', html_payload)
        self.assertIn('class="overlay overlay--wb overlay--wb-full"', html_payload)
        self.assertNotIn('class="wb-stage', html_payload)

    def test_world_boss_split_html_outputs_stage_and_info_separately(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                    "kv: 状態 | 戦闘中 / 残り 22秒",
                    "kv: 参加人数 | 3人",
                    "kv: HP | 480/1500 (32%)",
                ]
            )
        )

        info_html_payload = writer._render_html(
            "Alice / !wb",
            "2026-03-24 12:00:00",
            entries,
            view_mode="info",
        )
        wb_html_payload = writer._render_html(
            "Alice / !wb",
            "2026-03-24 12:00:00",
            entries,
            view_mode="wb",
        )

        self.assertIn('class="overlay overlay--wb overlay--wb-full"', info_html_payload)
        self.assertNotIn('class="wb-stage', info_html_payload)
        self.assertIn('class="wb-stage ', wb_html_payload)
        self.assertIn("wb-stage--idle", wb_html_payload)
        self.assertIn("wb-theme--crimson", wb_html_payload)
        self.assertIn("wb-stage--active", wb_html_payload)
        self.assertIn("wb-stage--phase-3", wb_html_payload)
        self.assertIn("wb-stage--visual-only", wb_html_payload)
        self.assertNotIn('class="wb-stage__hud"', wb_html_payload)
        self.assertNotIn('class="overlay overlay--wb', wb_html_payload)
        self.assertIn('data-has-wb-stage="1"', wb_html_payload)
        self.assertIn('wb-stage-stale', wb_html_payload)
        self.assertIn('window.setInterval(syncWbVisibility, 1000)', wb_html_payload)
        self.assertIn('.wb-stage--visual-only .wb-stage__backdrop,', wb_html_payload)
        self.assertIn('filter: none;', wb_html_payload)

    def test_world_boss_overlay_uses_configured_visual_for_moon_ruin_overseer(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_boss_configured_moon"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "2.png").touch()
        writer = DetailOverlayWriter(str(output_dir / "obs_detail_overlay.html"), "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 月蝕機卿ネメシス / 崩月廃都の監督者",
                    "kv: 状態 | 戦闘中 / 残り 40秒",
                    "kv: 参加人数 | 4人",
                    "kv: HP | 1200/2100 (57%)",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-24 12:00:00", entries)

        self.assertIn('src="2.png"', html_payload)
        self.assertIn("wb-theme--moon", html_payload)

    def test_world_boss_overlay_uses_configured_visual_for_witch_style_boss(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_boss_configured_witch"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "3.png").touch()
        writer = DetailOverlayWriter(str(output_dir / "obs_detail_overlay.html"), "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 魔弾妃ヘクセミア / ウィッチスタイル",
                    "kv: 状態 | 戦闘中 / 残り 51秒",
                    "kv: 参加人数 | 4人",
                    "kv: HP | 3100/5000 (62%)",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-27 12:00:00", entries)

        self.assertIn('src="3.png"', html_payload)

    def test_world_boss_overlay_uses_configured_visual_for_fencer_style_boss(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_boss_configured_fencer"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "4.png").touch()
        writer = DetailOverlayWriter(str(output_dir / "obs_detail_overlay.html"), "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 迅剣姫ラファエラ / フェンサースタイル",
                    "kv: 状態 | 戦闘中 / 残り 44秒",
                    "kv: 参加人数 | 5人",
                    "kv: HP | 4500/8000 (56%)",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-27 12:00:00", entries)

        self.assertIn('src="4.png"', html_payload)

    def test_world_boss_overlay_falls_back_to_shared_visual_when_specific_file_missing(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_boss_fallback"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "world_boss_visual.png").touch()
        writer = DetailOverlayWriter(str(output_dir / "obs_detail_overlay.html"), "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                    "kv: 状態 | 戦闘中 / 残り 22秒",
                    "kv: 参加人数 | 3人",
                    "kv: HP | 480/1500 (32%)",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-24 12:00:00", entries)

        self.assertIn("world_boss_visual.png", html_payload)

    def test_world_boss_overlay_resolves_repo_asset_relative_to_runtime_html(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_runtime_assets"
        runtime_dir = output_dir / "runtime"
        asset_dir = output_dir / "assets" / "world_boss"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "4.png").touch()
        writer = DetailOverlayWriter(str(runtime_dir / "obs_detail_overlay.html"), "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "kv: WB | 迅剣姫ラファエラ / フェンサースタイル",
                    "kv: 状態 | 戦闘中 / 残り 44秒",
                    "kv: 参加人数 | 5人",
                    "kv: HP | 4500/8000 (56%)",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-31 12:00:00", entries)

        self.assertIn('src="../assets/world_boss/4.png"', html_payload)

    def test_non_world_boss_html_marks_stage_as_hidden(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: 次の一手",
                    "kv: 要約 | 朝の森へ向かう",
                ]
            )
        )

        html_payload = writer._render_html(
            "Alice / !me",
            "2026-03-24 12:00:00",
            entries,
            view_mode="combined",
            generated_at_epoch=1711249200.0,
        )

        self.assertIn('data-has-wb-stage="0"', html_payload)
        self.assertIn('data-generated-at-epoch="1711249200.000"', html_payload)

    def test_show_writes_split_html_files(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show(
            "Alice / !wb",
            [
                "section: ワールドボス",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )

        self.assertTrue((output_dir / "obs_detail_overlay.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_content.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_info.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_info_content.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_wb.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_wb_content.html").is_file())
        self.assertTrue((output_dir / "obs_detail_overlay_wb_state.js").is_file())

    def test_show_writes_world_boss_state_payload(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_state"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show_wb_html(
            "ワールドボス / 灼甲帝ヴァルカラン",
            [
                "section: ワールドボス",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )

        state_payload = (output_dir / "obs_detail_overlay_wb_state.js").read_text(encoding="utf-8")

        self.assertIn("window.__WB_OVERLAY_STATE__", state_payload)
        self.assertIn("\"showStage\": true", state_payload)
        self.assertIn("\"bossName\": \"灼甲帝ヴァルカラン\"", state_payload)
        self.assertIn("\"bossId\": \"crimson_beetle_emperor\"", state_payload)
        self.assertIn("\"phaseLabel\": \"PHASE 3\"", state_payload)
        self.assertIn("\"rankingChipText\": \"\"", state_payload)
        self.assertIn("\"timeRemainingSec\": 0", state_payload)
        self.assertIn("\"timeCritical\": false", state_payload)
        self.assertIn("\"wb-theme--crimson\"", state_payload)
        self.assertIn("\"wb-stage--active\"", state_payload)
        self.assertIn("\"wb-stage--phase-3\"", state_payload)

    def test_show_writes_world_boss_event_summary_into_state_payload(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_state_event"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show_wb_html(
            "ワールドボス / 月蝕機卿ネメシス",
            [
                "section: ワールドボス",
                "kv: WB | 月蝕機卿ネメシス / 崩月廃都の監督者",
                "kv: 状態 | 戦闘中 / 残り 41秒",
                "kv: 参加人数 | 4人",
                "kv: HP | 1200/2100 (57%)",
                "section: 直近ログ",
                "kv: 1 | 戦闘開始: 月蝕機卿ネメシス / HP 2100",
                "kv: 2 | WB全体攻撃: Alice に 28ダメ",
            ],
        )

        state_payload = (output_dir / "obs_detail_overlay_wb_state.js").read_text(encoding="utf-8")

        self.assertIn("\"eventKind\": \"aoe\"", state_payload)
        self.assertIn("\"eventText\": \"WB全体攻撃: Alice に 28ダメ\"", state_payload)
        self.assertIn("\"eventClasses\": [\"wb-stage__event\", \"wb-stage__event--aoe\"]", state_payload)
        self.assertIn("\"bossId\": \"moon_ruin_overseer\"", state_payload)

    def test_show_writes_world_boss_state_payload_prefers_meta_state_values(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_state_meta"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show_wb_html(
            "ワールドボス / 灼甲帝ヴァルカラン",
            [
                "section: ワールドボス",
                "meta: wb_phase | active",
                "meta: wb_phase_id | last_stand",
                "meta: wb_phase_label | LAST STAND",
                "meta: wb_boss_id | crimson_beetle_emperor",
                "meta: wb_boss_name | 灼甲帝ヴァルカラン",
                "meta: wb_boss_title | 紅蓮を喰らう甲殻王",
                "meta: wb_event_kind | ranking",
                "meta: wb_event_text | 総合貢献王争い / #1 Alice 120 / #2 Bob 112 / 差 8",
                "meta: wb_status_text | 戦闘中 / 残り 22秒",
                "meta: wb_hp_text | 480/1500 (32%)",
                "meta: wb_time_remaining_sec | 22",
                "meta: wb_time_total_sec | 180",
                "meta: wb_time_critical | 1",
                "meta: wb_presentation_trigger | last_stand_close_race",
                "meta: wb_presentation_tone | danger",
                "meta: wb_leader_score | 120",
                "meta: wb_runner_up_score | 112",
                "meta: wb_leader_gap | 8",
                "meta: wb_participants_text | 3人",
                "meta: wb_ranking_text | #1 Alice 貢献120 / #2 Bob 貢献112",
                "meta: wb_show_stage | 1",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )

        state_payload = (output_dir / "obs_detail_overlay_wb_state.js").read_text(encoding="utf-8")

        self.assertIn("\"phase\": \"active\"", state_payload)
        self.assertIn("\"phaseId\": \"last_stand\"", state_payload)
        self.assertIn("\"bossName\": \"灼甲帝ヴァルカラン\"", state_payload)
        self.assertIn("\"bossTitle\": \"紅蓮を喰らう甲殻王\"", state_payload)
        self.assertIn("\"phaseLabel\": \"LAST STAND\"", state_payload)
        self.assertIn("\"eventKind\": \"ranking\"", state_payload)
        self.assertIn("\"eventText\": \"総合貢献王争い / #1 Alice 120 / #2 Bob 112 / 差 8\"", state_payload)
        self.assertIn("\"eventClasses\": [\"wb-stage__event\", \"wb-stage__event--ranking\"]", state_payload)
        self.assertIn("\"rankingText\": \"#1 Alice 貢献120 / #2 Bob 貢献112\"", state_payload)
        self.assertIn("\"timeRemainingSec\": 22", state_payload)
        self.assertIn("\"timeTotalSec\": 180", state_payload)
        self.assertIn("\"timeCritical\": true", state_payload)
        self.assertIn("\"presentationTrigger\": \"last_stand_close_race\"", state_payload)
        self.assertIn("\"presentationTone\": \"danger\"", state_payload)
        self.assertIn("\"leaderScore\": 120", state_payload)
        self.assertIn("\"runnerUpScore\": 112", state_payload)
        self.assertIn("\"leaderGap\": 8", state_payload)
        self.assertIn("\"rankingChipText\": \"順位 #1 Alice 貢献120 / #2 Bob 貢献112\"", state_payload)
        self.assertIn("\"rankingChipClasses\": [\"wb-stage__chip\"]", state_payload)
        self.assertIn("\"raceFocusActive\": false", state_payload)
        self.assertIn("\"raceText\": \"\"", state_payload)

    def test_show_writes_world_boss_announce_state_payload_with_fallback_presentation(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_state_announce"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        wb_content_path = output_dir / "obs_detail_overlay_wb_content.html"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show_wb_html(
            "ワールドボス / 灼甲帝ヴァルカラン",
            [
                "section: ワールドボス",
                "meta: wb_phase | announce",
                "meta: wb_phase_id | announce",
                "meta: wb_boss_id | crimson_beetle_emperor",
                "meta: wb_boss_name | 灼甲帝ヴァルカラン",
                "meta: wb_boss_title | 紅蓮を喰らう甲殻王",
                "meta: wb_event_kind | announce",
                "meta: wb_event_text | 出現予告: 灼甲帝ヴァルカラン",
                "meta: wb_status_text | 出現予告 / 募集開始まで 5秒",
                "meta: wb_show_stage | 1",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 出現予告 / 募集開始まで 5秒",
                "kv: 参加人数 | 0人",
            ],
        )

        state_payload = (output_dir / "obs_detail_overlay_wb_state.js").read_text(encoding="utf-8")
        wb_content = wb_content_path.read_text(encoding="utf-8")

        self.assertIn("\"presentationTrigger\": \"boss_spawn\"", state_payload)
        self.assertIn("\"presentationTone\": \"spotlight\"", state_payload)
        self.assertIn("\"eventClasses\": [\"wb-stage__event\", \"wb-stage__event--announce\"]", state_payload)
        self.assertIn("wb-stage--announce", wb_content)
        self.assertIn("wb-stage--trigger-boss-spawn", wb_content)
        self.assertIn("wb-stage--tone-spotlight", wb_content)

    def test_show_writes_world_boss_race_focus_meta_into_state_payload(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_state_race"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        wb_content_path = output_dir / "obs_detail_overlay_wb_content.html"
        if wb_content_path.exists():
            wb_content_path.unlink()
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show_wb_html(
            "ワールドボス / 灼甲帝ヴァルカラン",
            [
                "section: ワールドボス",
                "meta: wb_phase | active",
                "meta: wb_phase_id | last_stand",
                "meta: wb_boss_id | crimson_beetle_emperor",
                "meta: wb_race_focus_active | 1",
                "meta: wb_race_text | #1 Alice 120 / #2 Bob 112 / 差 8",
                "meta: wb_status_text | 戦闘中 / 残り 22秒",
                "meta: wb_hp_text | 480/1500 (32%)",
                "meta: wb_time_remaining_sec | 22",
                "meta: wb_time_total_sec | 180",
                "meta: wb_time_critical | 1",
                "meta: wb_presentation_trigger | last_stand_close_race",
                "meta: wb_presentation_tone | danger",
                "meta: wb_leader_gap | 8",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )

        state_payload = (output_dir / "obs_detail_overlay_wb_state.js").read_text(encoding="utf-8")
        wb_content = wb_content_path.read_text(encoding="utf-8")

        self.assertIn("\"raceFocusActive\": true", state_payload)
        self.assertIn("\"raceText\": \"#1 Alice 120 / #2 Bob 112 / 差 8\"", state_payload)
        self.assertIn("\"timeCritical\": true", state_payload)
        self.assertIn("\"presentationTrigger\": \"last_stand_close_race\"", state_payload)
        self.assertIn("\"presentationTone\": \"danger\"", state_payload)
        self.assertIn("\"leaderGap\": 8", state_payload)
        self.assertIn("\"rankingChipText\": \"争い #1 Alice 120 / #2 Bob 112 / 差 8\"", state_payload)
        self.assertIn("\"rankingChipClasses\": [\"wb-stage__chip\", \"wb-stage__chip--race\"]", state_payload)
        self.assertIn("wb-stage--time-critical", wb_content)
        self.assertIn("wb-stage--race-focus", wb_content)
        self.assertIn("wb-stage--trigger-last-stand-close-race", wb_content)
        self.assertIn("wb-stage--tone-danger", wb_content)

    def test_world_boss_result_stage_emphasizes_result_summary(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: ワールドボス",
                    "meta: wb_phase | resolving",
                    "meta: wb_phase_id | boss_down",
                    "meta: wb_boss_id | crimson_beetle_emperor",
                    "meta: wb_boss_name | 灼甲帝ヴァルカラン",
                    "meta: wb_boss_title | 紅蓮を喰らう甲殻王",
                    "meta: wb_status_text | 結果確定中",
                    "meta: wb_result_text | 灼甲帝ヴァルカラン / 討伐成功",
                    "meta: wb_event_kind | victory",
                    "meta: wb_event_text | 総合貢献王 Alice / 貢献 750",
                    "meta: wb_ranking_text | #1 Alice 貢献750",
                    "meta: wb_show_stage | 1",
                    "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                    "kv: 状態 | 結果確定中",
                    "kv: 結果 | 灼甲帝ヴァルカラン / 討伐成功",
                    "kv: 順位 | #1 Alice 貢献750",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-31 12:00:00", entries)

        self.assertIn("wb-stage__chip--result", html_payload)
        self.assertIn("wb-stage--tone-victory", html_payload)
        self.assertIn("wb-stage--trigger-victory", html_payload)
        self.assertIn('class="wb-stage__title">灼甲帝ヴァルカラン / 討伐成功</p>', html_payload)

    def test_show_keeps_existing_wb_html_when_non_world_boss_overlay_updates(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_persist"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show(
            "Alice / !wb",
            [
                "section: ワールドボス",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )
        wb_content_path = output_dir / "obs_detail_overlay_wb_content.html"
        wb_content_before = wb_content_path.read_text(encoding="utf-8")

        writer.show(
            "Alice / !me",
            [
                "section: 次の一手",
                "kv: 要約 | 朝の森へ向かう",
            ],
        )
        wb_content_after = wb_content_path.read_text(encoding="utf-8")

        self.assertEqual(wb_content_before, wb_content_after)
        self.assertIn('class="wb-stage ', wb_content_after)
        self.assertIn("wb-stage--idle", wb_content_after)
        self.assertIn("wb-stage--active", wb_content_after)
        self.assertIn("wb-stage--visual-only", wb_content_after)

    def test_show_can_skip_world_boss_variant_rewrite_for_spawn_card(self) -> None:
        test_tmp_root = Path(__file__).resolve().parent
        output_dir = test_tmp_root / "tmp_detail_overlay_writer_spawn_skip"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / "obs_detail_overlay.html"
        text_path = output_dir / "obs_detail_overlay.txt"
        writer = DetailOverlayWriter(str(html_path), str(text_path))

        writer.show(
            "Alice / !wb",
            [
                "section: ワールドボス",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 戦闘中 / 残り 22秒",
                "kv: 参加人数 | 3人",
                "kv: HP | 480/1500 (32%)",
            ],
        )
        wb_content_path = output_dir / "obs_detail_overlay_wb_content.html"
        wb_state_path = output_dir / "obs_detail_overlay_wb_state.js"
        wb_content_before = wb_content_path.read_text(encoding="utf-8")
        wb_state_before = wb_state_path.read_text(encoding="utf-8")

        writer.show(
            "ワールドボス出現 / 灼甲帝ヴァルカラン",
            [
                "section: ワールドボス通知",
                "alert: kv: 通知 | WB募集開始 / 灼甲帝ヴァルカラン / 120秒 / `!wb参加`",
                "kv: WB | 灼甲帝ヴァルカラン / 紅蓮を喰らう甲殻王",
                "kv: 状態 | 募集中",
                "kv: 参加人数 | 0人",
            ],
            include_world_boss_variant=False,
        )

        wb_content_after = wb_content_path.read_text(encoding="utf-8")
        wb_state_after = wb_state_path.read_text(encoding="utf-8")

        self.assertEqual(wb_content_before, wb_content_after)
        self.assertEqual(wb_state_before, wb_state_after)


if __name__ == "__main__":
    unittest.main()
