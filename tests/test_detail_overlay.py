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
        self.assertNotIn("overlay-frame-a", wb_shell_payload)
        self.assertIn("wb-stage-art", wb_shell_payload)

    def test_structured_overlay_lines_render_clean_text_and_html(self) -> None:
        writer = DetailOverlayWriter("unused.html", "unused.txt")
        entries = writer._parse_entries(
            writer._sanitize_lines(
                [
                    "section: 次の一手",
                    "kv: 要約 | 朝の森へ向かう",
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

        self.assertIn('class="section"', html_payload)
        self.assertIn('class="line line--kv"', html_payload)
        self.assertIn('class="line line--kv line--alert"', html_payload)
        self.assertIn("通常行も残す", html_payload)

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
                    "kv: 2 | WB攻撃: Alice に 34ダメ",
                ]
            )
        )

        html_payload = writer._render_html("Alice / !wb", "2026-03-24 12:00:00", entries)

        self.assertIn('class="wb-layout"', html_payload)
        self.assertIn("灼甲帝ヴァルカラン", html_payload)
        self.assertIn("紅蓮を喰らう甲殻王", html_payload)
        self.assertIn("wb-stage--active", html_payload)
        self.assertIn("wb-stage--attack", html_payload)
        self.assertIn("wb-stage__hp-fill", html_payload)
        self.assertIn("wb-stage__motion", html_payload)
        self.assertIn("wb-stage__pose", html_payload)
        self.assertIn("wb-stage__shadow", html_payload)
        self.assertIn("wb-stage__impact", html_payload)

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
        self.assertIn('class="wb-stage wb-stage--idle wb-stage--active wb-stage--visual-only"', wb_html_payload)
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
        self.assertIn("\"stageClasses\": [\"wb-stage--idle\", \"wb-stage--active\"]", state_payload)

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
        self.assertIn('class="wb-stage wb-stage--idle wb-stage--active wb-stage--visual-only"', wb_content_after)

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
