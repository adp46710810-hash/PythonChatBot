from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from typing import Iterable, List
from urllib.parse import quote

from .balance_data import WORLD_BOSSES
from .storage import atomic_write_text


@dataclass
class OverlayEntry:
    kind: str
    text: str = ""
    label: str = ""
    value: str = ""
    alert: bool = False


@dataclass
class WorldBossOverlayState:
    boss_name: str = "WORLD BOSS"
    boss_title: str = ""
    phase: str = ""
    phase_id: str = ""
    status_text: str = ""
    result_text: str = ""
    hp_text: str = ""
    hp_current: int = 0
    hp_max: int = 0
    hp_pct: int = 0
    participants_text: str = ""
    ranking_text: str = ""
    recent_logs: List[str] = field(default_factory=list)
    stage_classes: List[str] = field(default_factory=list)
    show_stage: bool = True
    visual_url: str = ""
    boss_id: str = ""
    phase_label: str = ""
    event_text: str = ""
    event_kind: str = ""
    race_focus_active: bool = False
    race_text: str = ""


@dataclass
class DetailOverlayWriter:
    html_path: str
    text_path: str
    max_lines: int = 240
    wb_stale_hide_after_sec: float = 8.0

    def _prepare_render_payload(
        self,
        title: str,
        lines: Iterable[str],
    ) -> tuple[List[OverlayEntry], str, float, str]:
        cleaned_lines = self._sanitize_lines(lines)
        entries = self._parse_entries(cleaned_lines)
        generated_at = datetime.now()
        timestamp = generated_at.strftime("%Y-%m-%d %H:%M:%S")
        generated_at_epoch = generated_at.timestamp()
        text_payload = self._render_text(title, timestamp, entries)
        return entries, timestamp, generated_at_epoch, text_payload

    def _write_html_variants(
        self,
        title: str,
        entries: List[OverlayEntry],
        timestamp: str,
        generated_at_epoch: float,
        variants: Iterable[str],
    ) -> None:
        is_world_boss = self._is_world_boss_overlay(title, entries)
        world_boss_state = self._build_world_boss_state(title, entries) if is_world_boss else None
        for variant in variants:
            html_payload = self._render_html(
                title,
                timestamp,
                entries,
                view_mode=variant,
                generated_at_epoch=generated_at_epoch,
            )
            atomic_write_text(self._content_html_path(variant), html_payload)
            if variant == "wb":
                atomic_write_text(
                    self._state_variant_path(variant),
                    self._render_wb_state_payload(title, generated_at_epoch, world_boss_state),
                )
            self._write_shell_html_if_missing(title, variant=variant)

    def _write_shell_html_if_missing(self, title: str, *, variant: str = "combined") -> None:
        shell_path = Path(self._html_variant_path(variant))
        if shell_path.is_file():
            return
        atomic_write_text(str(shell_path), self._render_shell_html(title, variant=variant))

    def show(
        self,
        title: str,
        lines: Iterable[str],
        *,
        include_world_boss_variant: bool = True,
    ) -> None:
        entries, timestamp, generated_at_epoch, text_payload = self._prepare_render_payload(
            title,
            lines,
        )
        atomic_write_text(self.text_path, text_payload)
        self._write_html_variants(
            title,
            entries,
            timestamp,
            generated_at_epoch,
            ("combined", "info"),
        )
        should_write_wb_variant = include_world_boss_variant and (
            self._is_world_boss_overlay(title, entries)
            or not Path(self._content_html_path("wb")).is_file()
        )
        if should_write_wb_variant:
            self._write_html_variants(
                title,
                entries,
                timestamp,
                generated_at_epoch,
                ("wb",),
            )

    def show_wb_html(self, title: str, lines: Iterable[str]) -> None:
        entries, timestamp, generated_at_epoch, _ = self._prepare_render_payload(title, lines)
        is_world_boss = self._is_world_boss_overlay(title, entries)
        world_boss_state = self._build_world_boss_state(title, entries) if is_world_boss else None

        atomic_write_text(
            self._state_variant_path("wb"),
            self._render_wb_state_payload(title, generated_at_epoch, world_boss_state),
        )
        if not Path(self._html_variant_path("wb")).is_file():
            self._write_shell_html_if_missing(title, variant="wb")
        if not Path(self._content_html_path("wb")).is_file():
            atomic_write_text(
                self._content_html_path("wb"),
                self._render_html(
                    title,
                    timestamp,
                    entries,
                    view_mode="wb",
                    generated_at_epoch=generated_at_epoch,
                ),
            )

    def _html_variant_path(self, variant: str = "combined") -> str:
        html_path = Path(self.html_path)
        suffix = html_path.suffix or ".html"
        stem = html_path.stem if variant == "combined" else f"{html_path.stem}_{variant}"
        return str(html_path.with_name(f"{stem}{suffix}"))

    def _content_html_path(self, variant: str = "combined") -> str:
        html_path = Path(self.html_path)
        suffix = html_path.suffix or ".html"
        stem = html_path.stem if variant == "combined" else f"{html_path.stem}_{variant}"
        return str(html_path.with_name(f"{stem}_content{suffix}"))

    def _state_variant_path(self, variant: str = "wb") -> str:
        html_path = Path(self.html_path)
        stem = html_path.stem if variant == "combined" else f"{html_path.stem}_{variant}"
        return str(html_path.with_name(f"{stem}_state.js"))

    def _render_shell_html(self, title: str, *, variant: str = "combined") -> str:
        safe_title = escape(title)
        if variant == "wb":
            state_name = quote(Path(self._state_variant_path(variant)).name, safe="/:._-%")
            return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>{safe_title}</title>
  <style>
    * {{
      box-sizing: border-box;
    }}

    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: transparent;
    }}

    body {{
      display: flex;
      align-items: stretch;
      justify-content: center;
      background: transparent;
      overflow: hidden;
      font-family: "BIZ UDPGothic", "Yu Gothic UI", "Hiragino Sans", sans-serif;
    }}

    .is-hidden {{
      display: none !important;
    }}

    .wb-stage-shell {{
      width: 100%;
      min-height: 100vh;
      display: flex;
      align-items: stretch;
      justify-content: center;
      overflow: hidden;
      background: transparent;
    }}

    .wb-stage {{
      position: relative;
      width: min(100%, 620px);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: visible;
      isolation: isolate;
      --wb-theme-top: rgba(255, 210, 140, 0.54);
      --wb-theme-left: rgba(255, 82, 82, 0.24);
      --wb-theme-right: rgba(32, 104, 255, 0.22);
      --wb-aura-core: rgba(255, 225, 167, 0.88);
      --wb-aura-edge: rgba(255, 139, 79, 0.18);
      --wb-impact-core: rgba(255, 242, 198, 0.42);
      --wb-impact-mid: rgba(255, 189, 111, 0.24);
      --wb-impact-edge: rgba(255, 122, 85, 0.12);
      --wb-bar-a: #f9735c;
      --wb-bar-b: #ffb357;
      --wb-bar-c: #ffe27f;
      --wb-phase-bg: rgba(15, 13, 24, 0.72);
      --wb-phase-border: rgba(255, 231, 197, 0.22);
      --wb-phase-text: rgba(255, 247, 234, 0.98);
      --wb-event-bg: rgba(14, 12, 22, 0.72);
      --wb-event-border: rgba(255, 231, 197, 0.22);
      --wb-event-text: rgba(255, 245, 233, 0.98);
      --wb-panel-glow: rgba(255, 182, 105, 0.24);
    }}

    .wb-stage.is-hidden {{
      display: none !important;
    }}

    .wb-stage.wb-theme--crimson {{
      --wb-theme-top: rgba(255, 173, 120, 0.58);
      --wb-theme-left: rgba(255, 88, 72, 0.30);
      --wb-theme-right: rgba(255, 216, 102, 0.20);
      --wb-aura-core: rgba(255, 214, 150, 0.92);
      --wb-aura-edge: rgba(255, 103, 72, 0.26);
      --wb-impact-core: rgba(255, 244, 194, 0.48);
      --wb-impact-mid: rgba(255, 164, 78, 0.28);
      --wb-impact-edge: rgba(255, 92, 74, 0.16);
      --wb-bar-a: #ff6f4e;
      --wb-bar-b: #ffb03f;
      --wb-bar-c: #ffe182;
      --wb-panel-glow: rgba(255, 131, 74, 0.28);
    }}

    .wb-stage.wb-theme--moon {{
      --wb-theme-top: rgba(182, 225, 255, 0.54);
      --wb-theme-left: rgba(94, 168, 255, 0.22);
      --wb-theme-right: rgba(183, 209, 255, 0.30);
      --wb-aura-core: rgba(214, 240, 255, 0.90);
      --wb-aura-edge: rgba(118, 171, 255, 0.20);
      --wb-impact-core: rgba(225, 247, 255, 0.42);
      --wb-impact-mid: rgba(120, 182, 255, 0.24);
      --wb-impact-edge: rgba(166, 212, 255, 0.16);
      --wb-bar-a: #66a4ff;
      --wb-bar-b: #7fd8ff;
      --wb-bar-c: #d5f3ff;
      --wb-panel-glow: rgba(116, 182, 255, 0.26);
    }}

    .wb-stage.wb-theme--witch {{
      --wb-theme-top: rgba(255, 196, 148, 0.52);
      --wb-theme-left: rgba(198, 88, 68, 0.24);
      --wb-theme-right: rgba(255, 235, 167, 0.22);
      --wb-aura-core: rgba(255, 226, 187, 0.90);
      --wb-aura-edge: rgba(197, 78, 56, 0.22);
      --wb-impact-core: rgba(255, 240, 196, 0.42);
      --wb-impact-mid: rgba(255, 143, 94, 0.26);
      --wb-impact-edge: rgba(98, 12, 10, 0.18);
      --wb-bar-a: #f06b55;
      --wb-bar-b: #ffb26e;
      --wb-bar-c: #ffe2aa;
      --wb-panel-glow: rgba(244, 122, 84, 0.26);
    }}

    .wb-stage.wb-theme--fencer {{
      --wb-theme-top: rgba(255, 236, 178, 0.52);
      --wb-theme-left: rgba(216, 190, 128, 0.22);
      --wb-theme-right: rgba(245, 252, 255, 0.26);
      --wb-aura-core: rgba(255, 244, 211, 0.90);
      --wb-aura-edge: rgba(214, 191, 126, 0.20);
      --wb-impact-core: rgba(255, 251, 219, 0.44);
      --wb-impact-mid: rgba(255, 221, 136, 0.24);
      --wb-impact-edge: rgba(198, 176, 118, 0.14);
      --wb-bar-a: #e1bb66;
      --wb-bar-b: #f7d991;
      --wb-bar-c: #fff1c8;
      --wb-panel-glow: rgba(236, 210, 129, 0.26);
    }}

    .wb-stage__backdrop {{
      position: absolute;
      inset: 10% 6% 12%;
      border-radius: 42px;
      background:
        radial-gradient(circle at 50% 18%, var(--wb-theme-top), transparent 38%),
        radial-gradient(circle at 28% 66%, var(--wb-theme-left), transparent 42%),
        radial-gradient(circle at 74% 72%, var(--wb-theme-right), transparent 44%);
      filter: blur(34px);
      opacity: 0.84;
      transform: translate3d(0, 0, 0) scale(0.98);
      transform-origin: 50% 55%;
      animation: wb-backdrop-pulse 8.4s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite;
      pointer-events: none;
      z-index: 0;
    }}

    .wb-stage__panel {{
      position: relative;
      z-index: 1;
      width: min(100%, 560px);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      padding: clamp(18px, 2.2vh, 28px);
      overflow: hidden;
      background:
        linear-gradient(180deg, rgba(21, 20, 29, 0.12), rgba(12, 11, 18, 0.42)),
        linear-gradient(180deg, rgba(255, 248, 238, 0.18), rgba(255, 244, 233, 0.04));
      border: 1px solid rgba(255, 231, 197, 0.16);
      box-shadow:
        0 30px 80px rgba(12, 10, 24, 0.24),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
      backdrop-filter: blur(8px);
    }}

    .wb-stage__signal {{
      position: relative;
      z-index: 2;
      display: grid;
      gap: 10px;
      align-self: stretch;
      margin-top: clamp(16px, 2.2vh, 26px);
      pointer-events: none;
    }}

    .wb-stage__phase-row {{
      display: flex;
      justify-content: flex-start;
    }}

    .wb-stage__phase {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 7px 14px;
      border-radius: 999px;
      background: var(--wb-phase-bg);
      border: 1px solid var(--wb-phase-border);
      color: var(--wb-phase-text);
      font-size: clamp(11px, 0.95vw, 13px);
      line-height: 1.3;
      font-weight: 900;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      box-shadow:
        0 14px 32px rgba(8, 7, 14, 0.24),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
    }}

    .wb-stage__event {{
      width: fit-content;
      max-width: min(100%, 420px);
      padding: 10px 14px;
      border-radius: 18px;
      background: var(--wb-event-bg);
      border: 1px solid var(--wb-event-border);
      color: var(--wb-event-text);
      font-size: clamp(12px, 1.02vw, 14px);
      line-height: 1.45;
      font-weight: 800;
      box-shadow:
        0 16px 34px rgba(10, 8, 18, 0.28),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
      text-shadow: 0 1px 0 rgba(0, 0, 0, 0.18);
    }}

    .wb-stage__event--critical {{
      background: linear-gradient(180deg, rgba(118, 38, 10, 0.88), rgba(74, 18, 8, 0.92));
      border-color: rgba(255, 214, 136, 0.34);
    }}

    .wb-stage__event--aoe,
    .wb-stage__event--down,
    .wb-stage__event--enrage {{
      background: linear-gradient(180deg, rgba(120, 20, 18, 0.90), rgba(72, 12, 12, 0.94));
      border-color: rgba(255, 178, 146, 0.34);
    }}

    .wb-stage__event--recover {{
      background: linear-gradient(180deg, rgba(20, 94, 64, 0.84), rgba(12, 54, 42, 0.90));
      border-color: rgba(172, 244, 212, 0.28);
    }}

    .wb-stage__event--start,
    .wb-stage__event--recruiting {{
      background: linear-gradient(180deg, rgba(20, 68, 112, 0.84), rgba(14, 34, 62, 0.90));
      border-color: rgba(180, 224, 255, 0.28);
    }}

    .wb-stage__event--victory {{
      background: linear-gradient(180deg, rgba(120, 88, 16, 0.88), rgba(76, 50, 10, 0.92));
      border-color: rgba(255, 222, 146, 0.34);
    }}

    .wb-stage__event--timeout {{
      background: linear-gradient(180deg, rgba(56, 58, 70, 0.90), rgba(28, 30, 40, 0.94));
      border-color: rgba(196, 205, 223, 0.24);
    }}

    .wb-stage__event--ranking {{
      background: linear-gradient(180deg, rgba(90, 68, 22, 0.90), rgba(52, 38, 12, 0.94));
      border-color: rgba(255, 218, 132, 0.30);
    }}

    .wb-stage__figure-wrap {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      overflow: hidden;
      pointer-events: none;
    }}

    .wb-stage__aura {{
      position: absolute;
      inset: 12% 10% 24%;
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 50%, var(--wb-aura-core), var(--wb-aura-edge) 42%, transparent 72%);
      filter: blur(20px);
      opacity: 0.82;
      transform: translate3d(0, 0, 0) scale(0.98);
      animation: wb-aura-breathe 6.6s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      will-change: transform, opacity;
    }}

    .wb-stage__impact {{
      position: absolute;
      left: 50%;
      bottom: 28%;
      width: min(76%, 320px);
      aspect-ratio: 1;
      border-radius: 50%;
      background:
        radial-gradient(circle, var(--wb-impact-core) 0%, var(--wb-impact-mid) 24%, var(--wb-impact-edge) 42%, transparent 68%);
      filter: blur(8px);
      opacity: 0;
      transform: translate3d(-50%, 0, 0) scale(0.68);
      will-change: transform, opacity;
      mix-blend-mode: screen;
    }}

    .wb-stage__shadow {{
      position: absolute;
      left: 50%;
      bottom: clamp(20px, 3vh, 34px);
      width: min(72%, 280px);
      height: clamp(18px, 3vh, 28px);
      border-radius: 999px;
      background: radial-gradient(circle, rgba(8, 8, 16, 0.42) 0%, rgba(8, 8, 16, 0.18) 54%, transparent 78%);
      filter: blur(10px);
      opacity: 0.34;
      transform: translate3d(-50%, 0, 0) scaleX(1);
      animation: wb-shadow-drift 6.8s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      will-change: transform, opacity;
    }}

    .wb-stage__figure {{
      position: relative;
      width: min(100%, 520px);
      height: min(94vh, 1040px);
      display: flex;
      align-items: flex-end;
      justify-content: center;
      animation: wb-float 6.8s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      will-change: transform;
    }}

    .wb-stage__motion {{
      width: 100%;
      height: 100%;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      transform-origin: 52% 86%;
      animation: wb-idle-sway 8.8s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite;
      will-change: transform;
      backface-visibility: hidden;
    }}

    .wb-stage__pose {{
      width: 100%;
      height: 100%;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      transform-origin: 52% 86%;
      will-change: transform;
      backface-visibility: hidden;
    }}

    .wb-stage__art {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      object-position: center bottom;
      filter: none;
      transform: translateZ(0);
      backface-visibility: hidden;
      user-select: none;
    }}

    .wb-stage__art.is-hidden {{
      display: none;
    }}

    .wb-stage__fallback {{
      width: clamp(220px, 26vw, 360px);
      aspect-ratio: 3 / 4;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      border-radius: 32px;
      background:
        radial-gradient(circle at 30% 20%, rgba(255, 208, 133, 0.84), transparent 34%),
        radial-gradient(circle at 74% 22%, rgba(255, 87, 87, 0.50), transparent 36%),
        radial-gradient(circle at 50% 76%, rgba(50, 106, 255, 0.54), transparent 38%),
        linear-gradient(180deg, rgba(22, 19, 34, 0.94), rgba(12, 10, 20, 0.98));
      border: 1px solid rgba(255, 232, 198, 0.32);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.16),
        0 28px 58px rgba(10, 8, 20, 0.26);
    }}

    .wb-stage__fallback.is-hidden {{
      display: none;
    }}

    .wb-stage__fallback-main {{
      font-size: clamp(62px, 8vw, 96px);
      font-weight: 900;
      letter-spacing: 0.1em;
      color: rgba(255, 248, 240, 0.96);
      text-shadow: 0 12px 28px rgba(0, 0, 0, 0.26);
    }}

    .wb-stage__fallback-sub {{
      font-size: clamp(12px, 1vw, 14px);
      letter-spacing: 0.16em;
      font-weight: 700;
      color: rgba(255, 227, 185, 0.84);
    }}

    .wb-stage__status {{
      position: relative;
      z-index: 2;
      width: 100%;
      margin-top: auto;
      padding: clamp(16px, 1.8vh, 22px);
      border-radius: clamp(24px, 2vw, 30px);
      background:
        linear-gradient(180deg, rgba(14, 12, 22, 0.12), rgba(14, 12, 22, 0.72)),
        linear-gradient(180deg, rgba(255, 252, 247, 0.18), rgba(248, 235, 219, 0.06));
      border: 1px solid rgba(255, 235, 204, 0.18);
      box-shadow:
        0 24px 54px rgba(12, 10, 24, 0.22),
        0 0 0 1px rgba(255, 255, 255, 0.04),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(10px);
    }}

    .wb-stage__eyebrow {{
      margin: 0 0 8px;
      font-size: clamp(11px, 0.95vw, 13px);
      line-height: 1.4;
      font-weight: 900;
      letter-spacing: 0.18em;
      color: rgba(255, 228, 194, 0.86);
    }}

    .wb-stage__name {{
      margin: 0;
      font-size: clamp(30px, 2.8vw, 42px);
      line-height: 1.04;
      font-weight: 900;
      letter-spacing: 0.02em;
      color: #fffaf4;
      text-shadow: 0 10px 24px rgba(18, 14, 26, 0.34);
    }}

    .wb-stage__title {{
      margin: 10px 0 0;
      font-size: clamp(13px, 1.08vw, 16px);
      line-height: 1.45;
      font-weight: 600;
      color: rgba(255, 235, 208, 0.92);
    }}

    .wb-stage__hp {{
      margin-top: 16px;
    }}

    .wb-stage__hp-meta {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}

    .wb-stage__hp-label {{
      font-size: clamp(11px, 0.92vw, 13px);
      font-weight: 800;
      letter-spacing: 0.16em;
      color: rgba(255, 229, 194, 0.84);
    }}

    .wb-stage__hp-value {{
      font-size: clamp(12px, 1vw, 14px);
      font-weight: 800;
      color: #fff6ed;
    }}

    .wb-stage__hp-track {{
      position: relative;
      height: 12px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(22, 19, 34, 0.46);
      box-shadow: inset 0 1px 4px rgba(0, 0, 0, 0.24);
    }}

    .wb-stage__hp-fill {{
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--wb-bar-a), var(--wb-bar-b) 52%, var(--wb-bar-c));
      box-shadow:
        0 0 18px var(--wb-panel-glow),
        inset 0 1px 0 rgba(255, 255, 255, 0.24);
    }}

    .wb-stage__chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}

    .wb-stage__chip {{
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(17, 15, 26, 0.42);
      border: 1px solid rgba(255, 231, 197, 0.18);
      color: #fff8ef;
      font-size: clamp(11px, 0.94vw, 13px);
      line-height: 1.35;
      font-weight: 700;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
    }}

    .wb-stage__chip--race {{
      background: linear-gradient(180deg, rgba(92, 68, 20, 0.92), rgba(54, 38, 12, 0.96));
      border-color: rgba(255, 219, 138, 0.30);
      color: #fff7e8;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.12),
        0 10px 24px rgba(255, 176, 82, 0.16);
    }}

    .wb-stage__chip--race {{
      background: linear-gradient(180deg, rgba(92, 68, 20, 0.92), rgba(54, 38, 12, 0.96));
      border-color: rgba(255, 219, 138, 0.30);
      color: #fff7e8;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.12),
        0 10px 24px rgba(255, 176, 82, 0.16);
    }}

    .wb-stage--recruiting .wb-stage__figure {{
      animation-duration: 6.2s;
    }}

    .wb-stage--recruiting .wb-stage__backdrop,
    .wb-stage--recruiting .wb-stage__aura {{
      animation-duration: 5.8s;
    }}

    .wb-stage--recruiting .wb-stage__motion {{
      animation-duration: 7.2s;
    }}

    .wb-stage--attack .wb-stage__pose {{
      animation: wb-attack 2.6s cubic-bezier(0.24, 0.78, 0.22, 1.0) infinite;
    }}

    .wb-stage--attack .wb-stage__impact,
    .wb-stage--impacting .wb-stage__impact {{
      animation: wb-impact-flash 2.6s cubic-bezier(0.18, 0.88, 0.22, 1.0) infinite;
    }}

    .wb-stage--phase-2 .wb-stage__panel {{
      box-shadow:
        0 30px 80px rgba(12, 10, 24, 0.26),
        0 0 46px var(--wb-panel-glow),
        inset 0 0 0 1px rgba(255, 255, 255, 0.06);
    }}

    .wb-stage--phase-3 .wb-stage__backdrop {{
      filter: blur(38px);
      opacity: 0.9;
    }}

    .wb-stage--last-stand .wb-stage__panel {{
      border-color: rgba(255, 214, 170, 0.34);
      box-shadow:
        0 30px 80px rgba(36, 8, 18, 0.34),
        0 0 58px rgba(255, 122, 76, 0.18),
        inset 0 0 0 1px rgba(255, 214, 170, 0.10);
    }}

    .wb-stage--last-stand .wb-stage__phase {{
      letter-spacing: 0.22em;
    }}

    .wb-stage--race-focus .wb-stage__status {{
      border-color: rgba(255, 221, 154, 0.28);
      box-shadow:
        0 24px 54px rgba(12, 10, 24, 0.22),
        0 0 0 1px rgba(255, 221, 154, 0.08),
        inset 0 1px 0 rgba(255, 250, 224, 0.14);
    }}

    .wb-stage--aoe .wb-stage__impact {{
      animation: wb-impact-aoe 1.8s cubic-bezier(0.2, 0.88, 0.24, 1.0) infinite;
    }}

    .wb-stage--critical .wb-stage__event,
    .wb-stage--victory-flash .wb-stage__event,
    .wb-stage--timeout-flash .wb-stage__event,
    .wb-stage--enrage-flash .wb-stage__event,
    .wb-stage--recruiting-flash .wb-stage__event {{
      animation: wb-banner-flash 1.05s ease-in-out infinite alternate;
    }}

    .wb-stage--downed .wb-stage__status {{
      border-color: rgba(255, 184, 152, 0.28);
      box-shadow:
        0 24px 54px rgba(30, 8, 16, 0.30),
        inset 0 1px 0 rgba(255, 215, 193, 0.10);
    }}

    .wb-stage--recover .wb-stage__status {{
      border-color: rgba(170, 244, 210, 0.26);
      box-shadow:
        0 24px 54px rgba(10, 32, 24, 0.24),
        inset 0 1px 0 rgba(210, 255, 233, 0.10);
    }}

    .wb-stage--victory .wb-stage__figure {{
      animation-duration: 7.4s;
    }}

    .wb-stage--victory .wb-stage__pose {{
      animation: wb-victory 5.8s cubic-bezier(0.34, 0.08, 0.26, 0.98) infinite;
    }}

    .wb-stage--timeout .wb-stage__pose {{
      animation: wb-timeout 6.2s cubic-bezier(0.38, 0.06, 0.3, 0.98) infinite;
    }}

    .wb-stage--timeout .wb-stage__status {{
      border-color: rgba(190, 198, 218, 0.22);
    }}

    @keyframes wb-float {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); }}
      18% {{ transform: translate3d(0, -4px, 0) scale(1.002); }}
      38% {{ transform: translate3d(0, -11px, 0) scale(1.008); }}
      58% {{ transform: translate3d(0, -7px, 0) scale(1.004); }}
      80% {{ transform: translate3d(0, -2px, 0) scale(1.001); }}
    }}

    @keyframes wb-idle-sway {{
      0%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg); }}
      22% {{ transform: translate3d(-4px, 0, 0) rotate(-0.35deg); }}
      48% {{ transform: translate3d(3px, -2px, 0) rotate(0.28deg); }}
      72% {{ transform: translate3d(1px, 0, 0) rotate(0.12deg); }}
    }}

    @keyframes wb-attack {{
      0%, 12%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg) scale(1); }}
      24% {{ transform: translate3d(-18px, 14px, 0) rotate(-1.8deg) scale(0.986); }}
      38% {{ transform: translate3d(26px, -18px, 0) rotate(1.9deg) scale(1.04); }}
      50% {{ transform: translate3d(42px, -12px, 0) rotate(2.6deg) scale(1.08); }}
      64% {{ transform: translate3d(16px, -6px, 0) rotate(0.8deg) scale(1.028); }}
      80% {{ transform: translate3d(2px, -1px, 0) rotate(0.14deg) scale(1.005); }}
    }}

    @keyframes wb-impact-flash {{
      0%, 20%, 100% {{ opacity: 0; transform: translate3d(-50%, 0, 0) scale(0.68); }}
      34% {{ opacity: 0.14; transform: translate3d(-50%, -3px, 0) scale(0.92); }}
      48% {{ opacity: 0.34; transform: translate3d(-50%, -6px, 0) scale(1.12); }}
      62% {{ opacity: 0.08; transform: translate3d(-50%, -4px, 0) scale(1.22); }}
    }}

    @keyframes wb-impact-aoe {{
      0%, 18%, 100% {{ opacity: 0; transform: translate3d(-50%, 0, 0) scale(0.54); }}
      34% {{ opacity: 0.18; transform: translate3d(-50%, -6px, 0) scale(0.96); }}
      50% {{ opacity: 0.32; transform: translate3d(-50%, -10px, 0) scale(1.32); }}
      72% {{ opacity: 0.04; transform: translate3d(-50%, -6px, 0) scale(1.58); }}
    }}

    @keyframes wb-victory {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); }}
      22% {{ transform: translate3d(0, -6px, 0) scale(1.01); }}
      46% {{ transform: translate3d(0, -16px, 0) scale(1.032); }}
      72% {{ transform: translate3d(0, -8px, 0) scale(1.014); }}
    }}

    @keyframes wb-timeout {{
      0%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg) scale(1); }}
      32% {{ transform: translate3d(-4px, 6px, 0) rotate(-0.6deg) scale(0.994); }}
      58% {{ transform: translate3d(-8px, 12px, 0) rotate(-1.1deg) scale(0.986); }}
      78% {{ transform: translate3d(-4px, 8px, 0) rotate(-0.5deg) scale(0.99); }}
    }}

    @keyframes wb-aura-breathe {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(0.98); opacity: 0.76; }}
      30% {{ transform: translate3d(0, -4px, 0) scale(1.04); opacity: 0.84; }}
      56% {{ transform: translate3d(0, -6px, 0) scale(1.09); opacity: 0.88; }}
      80% {{ transform: translate3d(0, -2px, 0) scale(1.03); opacity: 0.8; }}
    }}

    @keyframes wb-backdrop-pulse {{
      0%, 100% {{ opacity: 0.74; transform: translate3d(0, 0, 0) scale(0.98); }}
      28% {{ opacity: 0.8; transform: translate3d(-6px, -4px, 0) scale(1.005); }}
      58% {{ opacity: 0.86; transform: translate3d(4px, -8px, 0) scale(1.018); }}
      82% {{ opacity: 0.78; transform: translate3d(2px, -2px, 0) scale(0.992); }}
    }}

    @keyframes wb-shadow-drift {{
      0%, 100% {{ transform: translate3d(-50%, 0, 0) scaleX(1) scaleY(1); opacity: 0.34; }}
      38% {{ transform: translate3d(-50%, 0, 0) scaleX(0.94) scaleY(0.9); opacity: 0.26; }}
      64% {{ transform: translate3d(-50%, 0, 0) scaleX(0.97) scaleY(0.94); opacity: 0.29; }}
    }}

    @keyframes wb-banner-flash {{
      0% {{ transform: translate3d(0, 0, 0); box-shadow: 0 14px 32px rgba(8, 7, 14, 0.24); }}
      100% {{ transform: translate3d(0, -2px, 0); box-shadow: 0 18px 40px rgba(255, 164, 91, 0.24); }}
    }}

    @media (max-width: 720px) {{
      .wb-stage {{
        width: min(100%, 100vw);
      }}

      .wb-stage__panel {{
        width: 100%;
        padding: 14px;
      }}

      .wb-stage__figure {{
        width: min(100%, 420px);
        height: min(76vh, 680px);
      }}

      .wb-stage__name {{
        font-size: 26px;
      }}

      .wb-stage__event {{
        max-width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <main class="wb-stage-shell" aria-label="{safe_title}">
    <aside id="wb-stage" class="wb-stage is-hidden">
      <div class="wb-stage__backdrop"></div>
      <div class="wb-stage__panel">
        <div class="wb-stage__signal">
          <div id="wb-stage-phase-row" class="wb-stage__phase-row is-hidden">
            <span id="wb-stage-phase" class="wb-stage__phase"></span>
          </div>
          <div id="wb-stage-event" class="wb-stage__event is-hidden"></div>
        </div>
        <div class="wb-stage__figure-wrap">
          <div class="wb-stage__aura"></div>
          <div class="wb-stage__impact"></div>
          <div class="wb-stage__shadow"></div>
          <div class="wb-stage__figure">
            <div class="wb-stage__motion">
              <div class="wb-stage__pose">
                <img id="wb-stage-art" class="wb-stage__art is-hidden" alt="" loading="eager">
                <div id="wb-stage-fallback" class="wb-stage__fallback is-hidden" aria-hidden="true">
                  <span class="wb-stage__fallback-main">WB</span>
                  <span class="wb-stage__fallback-sub">WORLD BOSS</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="wb-stage__status">
          <p class="wb-stage__eyebrow">WORLD BOSS</p>
          <h1 id="wb-stage-name" class="wb-stage__name">WORLD BOSS</h1>
          <p id="wb-stage-title" class="wb-stage__title is-hidden"></p>
          <div id="wb-stage-hp" class="wb-stage__hp is-hidden">
            <div class="wb-stage__hp-meta">
              <span class="wb-stage__hp-label">HP</span>
              <span id="wb-stage-hp-value" class="wb-stage__hp-value"></span>
            </div>
            <div class="wb-stage__hp-track">
              <div id="wb-stage-hp-fill" class="wb-stage__hp-fill"></div>
            </div>
          </div>
          <div class="wb-stage__chips">
            <span id="wb-stage-status" class="wb-stage__chip is-hidden"></span>
            <span id="wb-stage-participants" class="wb-stage__chip is-hidden"></span>
            <span id="wb-stage-ranking" class="wb-stage__chip is-hidden"></span>
          </div>
        </div>
      </div>
    </aside>
  </main>
  <script>
    (() => {{
      const stage = document.getElementById("wb-stage");
      const art = document.getElementById("wb-stage-art");
      const fallback = document.getElementById("wb-stage-fallback");
      const phaseRow = document.getElementById("wb-stage-phase-row");
      const phaseLabel = document.getElementById("wb-stage-phase");
      const eventBanner = document.getElementById("wb-stage-event");
      const bossName = document.getElementById("wb-stage-name");
      const bossTitle = document.getElementById("wb-stage-title");
      const hpWrap = document.getElementById("wb-stage-hp");
      const hpValue = document.getElementById("wb-stage-hp-value");
      const hpFill = document.getElementById("wb-stage-hp-fill");
      const statusChip = document.getElementById("wb-stage-status");
      const participantsChip = document.getElementById("wb-stage-participants");
      const rankingChip = document.getElementById("wb-stage-ranking");
      const source = "{state_name}";
      let loading = false;
      let lastState = null;
      let currentVisualUrl = "";

      const setStageVisibility = (visible) => {{
        stage.classList.toggle("is-hidden", !visible);
      }};

      const applyVisual = (visualUrl, bossName) => {{
        if (!visualUrl) {{
          currentVisualUrl = "";
          art.removeAttribute("src");
          art.alt = bossName || "";
          art.classList.add("is-hidden");
          fallback.classList.remove("is-hidden");
          return;
        }}

        art.alt = bossName || "";
        fallback.classList.add("is-hidden");
        if (visualUrl === currentVisualUrl && art.getAttribute("src")) {{
          art.classList.remove("is-hidden");
          return;
        }}

        const preloader = new Image();
        preloader.onload = () => {{
          currentVisualUrl = visualUrl;
          art.src = visualUrl;
          art.classList.remove("is-hidden");
        }};
        preloader.onerror = () => {{
          currentVisualUrl = "";
          art.removeAttribute("src");
          art.classList.add("is-hidden");
          fallback.classList.remove("is-hidden");
        }};
        preloader.src = visualUrl;
      }};

      const applyChip = (element, text) => {{
        if (!element) {{
          return;
        }}
        const value = String(text || "").trim();
        element.textContent = value;
        element.classList.toggle("is-hidden", !value);
      }};

      const deriveStageClasses = (payload) => {{
        const classes = [];
        const safePhase = String(payload.phase || "").trim();
        const safePhaseId = String(payload.phaseId || "").trim();
        const safeEventKind = String(payload.eventKind || "").trim();
        const raceFocusActive = Boolean(payload.raceFocusActive);
        const eventClassMap = {{
          attack: "wb-stage--impacting",
          aoe: "wb-stage--aoe",
          critical: "wb-stage--critical",
          down: "wb-stage--downed",
          recover: "wb-stage--recover",
          enrage: "wb-stage--enrage-flash",
          start: "wb-stage--start",
          victory: "wb-stage--victory-flash",
          timeout: "wb-stage--timeout-flash",
          ranking: "wb-stage--ranking",
          recruiting: "wb-stage--recruiting-flash",
        }};
        if (safePhase === "recruiting") {{
          classes.push("wb-stage--recruiting");
        }} else if (safePhase === "active") {{
          classes.push("wb-stage--active", "wb-stage--phase-1");
        }} else if (safePhase === "cooldown") {{
          classes.push("wb-stage--cooldown");
        }}
        if (safePhaseId === "phase_2" || safePhaseId === "last_stand") {{
          classes.push("wb-stage--phase-2");
        }}
        if (safePhaseId === "last_stand") {{
          classes.push("wb-stage--phase-3", "wb-stage--last-stand", "wb-stage--enrage");
        }}
        if (["attack", "aoe", "start"].includes(safeEventKind)) {{
          classes.push("wb-stage--attack");
        }}
        if (safeEventKind === "down") {{
          classes.push("wb-stage--danger");
        }}
        if (safeEventKind === "enrage") {{
          classes.push("wb-stage--enrage");
        }}
        const eventClass = eventClassMap[safeEventKind];
        if (eventClass) {{
          classes.push(eventClass);
        }}
        if (raceFocusActive) {{
          classes.push("wb-stage--race-focus");
        }}
        return classes;
      }};

      const syncStaleVisibility = () => {{
        if (!lastState || !lastState.showStage || !(Number(lastState.generatedAtEpoch) > 0)) {{
          setStageVisibility(false);
          return;
        }}
        const staleHideAfterMs = Number(lastState.staleHideAfterMs || 8000);
        const stale = (Date.now() - (Number(lastState.generatedAtEpoch) * 1000)) > staleHideAfterMs;
        setStageVisibility(!stale);
      }};

      const applyState = (payload) => {{
        if (!payload || typeof payload !== "object") {{
          return;
        }}

        lastState = payload;
        const stageClasses = Array.isArray(payload.stageClasses) ? payload.stageClasses : [];
        const derivedStageClasses = deriveStageClasses(payload);
        const mergedStageClasses = Array.from(new Set(["wb-stage", ...stageClasses, ...derivedStageClasses]));
        stage.className = mergedStageClasses.join(" ").trim();
        const safeBossName = String(payload.bossName || "").trim() || "WORLD BOSS";
        const safeBossTitle = String(payload.bossTitle || "").trim();
        const safePhaseId = String(payload.phaseId || "").trim();
        const safePhaseLabel = String(payload.phaseLabel || "").trim() || {{
          entry_open: "ENTRY OPEN",
          phase_1: "PHASE 1",
          phase_2: "PHASE 2",
          last_stand: "LAST STAND",
          boss_down: "BOSS DOWN",
          time_over: "TIME OVER",
          cooldown: "COOLDOWN",
        }}[safePhaseId] || "";
        const safeEventText = String(payload.eventText || "").trim();
        const safeEventKind = String(payload.eventKind || "").trim();
        const safeHpText = String(payload.hpText || "").trim();
        const safeHpPct = Math.max(0, Math.min(100, Number(payload.hpPct || 0)));
        const safeRaceFocusActive = Boolean(payload.raceFocusActive);
        const safeRaceText = String(payload.raceText || "").trim();

        bossName.textContent = safeBossName;
        bossTitle.textContent = safeBossTitle;
        bossTitle.classList.toggle("is-hidden", !safeBossTitle);

        phaseLabel.textContent = safePhaseLabel;
        phaseRow.classList.toggle("is-hidden", !safePhaseLabel);

        eventBanner.textContent = safeEventText;
        eventBanner.className = [
          "wb-stage__event",
          safeEventKind ? `wb-stage__event--${{safeEventKind}}` : "",
          !safeEventText ? "is-hidden" : "",
        ]
          .filter(Boolean)
          .join(" ");

        hpValue.textContent = safeHpText;
        hpFill.style.width = `${{safeHpPct}}%`;
        hpWrap.classList.toggle("is-hidden", !safeHpText);

        applyChip(statusChip, String(payload.statusText || ""));
        applyChip(
          participantsChip,
          payload.participantsText ? `参加 ${{String(payload.participantsText)}}` : "",
        );
        applyChip(
          rankingChip,
          safeRaceFocusActive && safeRaceText
            ? `争い ${{safeRaceText}}`
            : payload.rankingText
              ? `順位 ${{String(payload.rankingText)}}`
              : "",
        );
        rankingChip.classList.toggle("wb-stage__chip--race", safeRaceFocusActive && !!safeRaceText);

        applyVisual(String(payload.visualUrl || ""), safeBossName);
        syncStaleVisibility();
      }};

      const loadState = () => {{
        if (loading) {{
          return;
        }}

        loading = true;
        const script = document.createElement("script");
        script.async = true;
        script.src = `${{source}}?v=${{Date.now()}}`;
        script.onload = () => {{
          loading = false;
          script.remove();
          applyState(window.__WB_OVERLAY_STATE__);
        }};
        script.onerror = () => {{
          loading = false;
          script.remove();
          syncStaleVisibility();
        }};
        document.head.appendChild(script);
      }};

      loadState();
      window.setInterval(loadState, 1000);
      window.setInterval(syncStaleVisibility, 1000);
    }})();
  </script>
</body>
</html>
"""

        content_name = quote(Path(self._content_html_path(variant)).name, safe="/:._-%")

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>{safe_title}</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: transparent;
    }}

    body {{
      position: relative;
    }}

    .overlay-host {{
      position: fixed;
      inset: 0;
      overflow: hidden;
      isolation: isolate;
    }}

    .overlay-frame {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
      background: transparent;
      opacity: 0;
      transition: opacity 90ms linear;
      pointer-events: none;
    }}

    .overlay-frame.is-visible {{
      opacity: 1;
    }}
  </style>
</head>
<body>
  <main class="overlay-host" aria-label="{safe_title}">
    <iframe id="overlay-frame-a" class="overlay-frame is-visible" title="{safe_title}" loading="eager"></iframe>
    <iframe id="overlay-frame-b" class="overlay-frame" title="{safe_title}" loading="eager"></iframe>
  </main>
  <script>
    (() => {{
      const frames = [
        document.getElementById("overlay-frame-a"),
        document.getElementById("overlay-frame-b"),
      ];
      const source = "{content_name}";
      let activeIndex = 0;
      let loading = false;

      const buildSource = () => `${{source}}?v=${{Date.now()}}`;
      const visibleFrame = () => frames[activeIndex];
      const hiddenFrame = () => frames[activeIndex === 0 ? 1 : 0];

      const swapFrame = () => {{
        if (loading) {{
          return;
        }}

        loading = true;
        const nextFrame = hiddenFrame();
        const currentFrame = visibleFrame();

        const handleLoad = () => {{
          nextFrame.removeEventListener("load", handleLoad);
          nextFrame.classList.add("is-visible");
          currentFrame.classList.remove("is-visible");
          activeIndex = activeIndex === 0 ? 1 : 0;
          loading = false;
        }};

        nextFrame.addEventListener("load", handleLoad);
        nextFrame.src = buildSource();
      }};

      frames[0].src = buildSource();
      window.setInterval(swapFrame, 2000);
    }})();
  </script>
</body>
</html>
"""

    def _render_wb_state_payload(
        self,
        title: str,
        generated_at_epoch: float,
        state: WorldBossOverlayState | None,
    ) -> str:
        payload = {
            "title": title,
            "generatedAtEpoch": float(generated_at_epoch or 0.0),
            "staleHideAfterMs": int(self.wb_stale_hide_after_sec * 1000),
            "showStage": bool(state and state.show_stage),
            "bossName": state.boss_name if state else "WORLD BOSS",
            "bossTitle": state.boss_title if state else "",
            "bossId": state.boss_id if state else "",
            "phase": state.phase if state else "",
            "phaseId": state.phase_id if state else "",
            "phaseLabel": state.phase_label if state else "",
            "eventText": state.event_text if state else "",
            "eventKind": state.event_kind if state else "",
            "statusText": state.status_text if state else "",
            "hpText": state.hp_text if state else "",
            "hpPct": state.hp_pct if state else 0,
            "participantsText": state.participants_text if state else "",
            "rankingText": state.ranking_text if state else "",
            "raceFocusActive": bool(state and state.race_focus_active),
            "raceText": state.race_text if state else "",
            "stageClasses": list(state.stage_classes) if state else [],
            "visualUrl": state.visual_url if state else "",
        }
        return f"window.__WB_OVERLAY_STATE__ = {json.dumps(payload, ensure_ascii=False)};\n"

    def _sanitize_lines(self, lines: Iterable[str]) -> List[str]:
        cleaned: List[str] = []
        for raw_line in lines:
            if raw_line is None:
                continue

            line = str(raw_line).replace("\r\n", "\n").replace("\r", "\n")
            normalized_parts = [split_line.rstrip() for split_line in line.split("\n")]
            if any(normalized_parts):
                cleaned.append("\n".join(normalized_parts).strip("\n"))
            else:
                cleaned.append("")

        cleaned = cleaned[-max(1, int(self.max_lines)) :]
        if not cleaned:
            return ["表示できる詳細がありません。"]
        return cleaned

    def _split_kv_payload(self, payload: str) -> tuple[str, str]:
        for separator in (" | ", "|"):
            if separator not in payload:
                continue
            label, value = payload.split(separator, 1)
            safe_label = label.strip()
            safe_value = value.strip()
            if safe_label and safe_value:
                return safe_label, safe_value
        return "", ""

    def _parse_entries(self, lines: List[str]) -> List[OverlayEntry]:
        entries: List[OverlayEntry] = []

        for raw_line in lines:
            line = raw_line
            alert = False

            if line.strip().startswith("alert:"):
                line = line.split(":", 1)[1].strip()
                alert = True

            if line.startswith("section:"):
                title = line.split(":", 1)[1].strip()
                if title:
                    entries.append(OverlayEntry(kind="section", text=title, alert=alert))
                continue

            if line.startswith("kv:"):
                payload = line.split(":", 1)[1].strip()
                label, value = self._split_kv_payload(payload)
                if label and value:
                    entries.append(
                        OverlayEntry(
                            kind="kv",
                            label=label,
                            value=value,
                            alert=alert,
                        )
                    )
                elif payload:
                    entries.append(OverlayEntry(kind="text", text=payload, alert=alert))
                else:
                    entries.append(OverlayEntry(kind="spacer"))
                continue

            if line.startswith("meta:"):
                payload = line.split(":", 1)[1].strip()
                label, value = self._split_kv_payload(payload)
                if label and value:
                    entries.append(
                        OverlayEntry(
                            kind="meta",
                            label=label,
                            value=value,
                        )
                    )
                continue

            if not line:
                entries.append(OverlayEntry(kind="spacer"))
                continue

            entries.append(OverlayEntry(kind="text", text=line, alert=alert))

        if not entries:
            return [OverlayEntry(kind="text", text="表示できる詳細がありません。")]
        return entries

    def _render_text(self, title: str, timestamp: str, entries: List[OverlayEntry]) -> str:
        lines = [
            f"# {title}",
            f"# updated_at: {timestamp}",
        ]

        for entry in entries:
            if entry.kind == "section":
                prefix = "! " if entry.alert else ""
                lines.append(f"[{prefix}{entry.text}]")
                continue
            if entry.kind == "meta":
                continue
            if entry.kind == "kv":
                prefix = "! " if entry.alert else ""
                lines.append(f"{prefix}{entry.label}: {entry.value}")
                continue
            if entry.kind == "spacer":
                lines.append("")
                continue
            prefix = "! " if entry.alert else ""
            lines.append(f"{prefix}{entry.text}")

        return "\n".join(lines).rstrip() + "\n"

    def _render_entries_html(self, entries: List[OverlayEntry]) -> str:
        rendered_lines = []
        text_line_no = 1
        for entry in entries:
            if entry.kind == "section":
                section_class = "section section--alert" if entry.alert else "section"
                rendered_lines.append(
                    f"      <div class=\"{section_class}\">"
                    f"<span class=\"section-text\">{escape(entry.text)}</span>"
                    "</div>"
                )
                continue

            if entry.kind == "meta":
                continue

            if entry.kind == "kv":
                line_class = "line line--kv line--alert" if entry.alert else "line line--kv"
                rendered_lines.append(
                    f"      <div class=\"{line_class}\">"
                    f"<span class=\"kv-label\">{escape(entry.label)}</span>"
                    f"<span class=\"kv-value\">{escape(entry.value)}</span>"
                    "</div>"
                )
                continue

            if entry.kind == "spacer":
                rendered_lines.append("      <div class=\"spacer\" aria-hidden=\"true\"></div>")
                continue

            line_class = "line line--alert" if entry.alert else "line"
            safe_line = escape(entry.text) if entry.text else "&nbsp;"
            rendered_lines.append(
                f"      <div class=\"{line_class}\">"
                f"<span class=\"line-no\">{text_line_no:03d}</span>"
                    f"<span class=\"line-text\">{safe_line}</span>"
                    "</div>"
            )
            text_line_no += 1

        return "\n".join(rendered_lines)

    def _is_world_boss_overlay(self, title: str, entries: List[OverlayEntry]) -> bool:
        if "ワールドボス" in str(title or ""):
            return True

        for entry in entries:
            if entry.kind == "section" and entry.text in {
                "ワールドボス",
                "ワールドボス通知",
                "WB結果",
                "WBランキング",
            }:
                return True
            if entry.kind == "kv" and entry.label in {"WB", "参加人数", "順位"}:
                return True
        return False

    def _find_first_kv_value(self, entries: List[OverlayEntry], label: str) -> str:
        for entry in entries:
            if entry.kind == "kv" and entry.label == label:
                return entry.value
        return ""

    def _find_first_meta_value(self, entries: List[OverlayEntry], label: str) -> str:
        for entry in entries:
            if entry.kind == "meta" and entry.label == label:
                return entry.value
        return ""

    def _collect_section_values(self, entries: List[OverlayEntry], section_name: str) -> List[str]:
        values: List[str] = []
        in_section = False

        for entry in entries:
            if entry.kind == "section":
                in_section = entry.text == section_name
                continue
            if not in_section:
                continue
            if entry.kind == "kv" and entry.value:
                values.append(entry.value)
                continue
            if entry.kind == "text" and entry.text:
                values.append(entry.text)

        return values

    def _extract_hp_metrics(self, hp_text: str) -> tuple[int, int, int]:
        match = re.search(r"(\d+)\s*/\s*(\d+)(?:\s*\((\d+)%\))?", hp_text or "")
        if not match:
            return 0, 0, 0

        current_hp = max(0, int(match.group(1)))
        max_hp = max(0, int(match.group(2)))
        if max_hp <= 0:
            return current_hp, max_hp, 0

        if match.group(3):
            hp_pct = max(0, min(100, int(match.group(3))))
        else:
            hp_pct = max(0, min(100, int(round((current_hp / max_hp) * 100))))
        return current_hp, max_hp, hp_pct

    def _split_boss_heading(self, heading: str) -> tuple[str, str]:
        safe_heading = str(heading or "").strip()
        if not safe_heading:
            return "WORLD BOSS", ""

        if " / " in safe_heading:
            boss_name, boss_title = safe_heading.split(" / ", 1)
            return boss_name.strip() or "WORLD BOSS", boss_title.strip()

        return safe_heading, ""

    def _guess_world_boss_id(self, boss_name: str) -> str:
        safe_boss_name = str(boss_name or "").strip()
        if not safe_boss_name:
            return ""

        for candidate_boss_id, boss in WORLD_BOSSES.items():
            candidate_name = str(boss.get("name", "") or "").strip()
            if candidate_name and candidate_name == safe_boss_name:
                return str(candidate_boss_id or "").strip()
        return ""

    def _get_world_boss_theme_class(self, boss_id: str) -> str:
        theme_classes = {
            "crimson_beetle_emperor": "wb-theme--crimson",
            "moon_ruin_overseer": "wb-theme--moon",
            "witch_style_hexamia": "wb-theme--witch",
            "fencer_style_raphaela": "wb-theme--fencer",
        }
        return theme_classes.get(str(boss_id or "").strip(), "wb-theme--default")

    def _build_world_boss_phase_label(
        self,
        *,
        title: str,
        status_text: str,
        result_text: str,
        hp_pct: int,
        phase_blob: str,
    ) -> str:
        safe_title = str(title or "").strip()
        safe_status = str(status_text or "").strip()
        safe_result = str(result_text or "").strip()
        safe_blob = str(phase_blob or "").strip()

        if "ワールドボス出現" in safe_title or "募集中" in safe_status:
            return "ENTRY OPEN"
        if "討伐成功" in safe_result or "討伐成功" in safe_blob:
            return "BOSS DOWN"
        if "時間切れ" in safe_result or "時間切れ" in safe_blob:
            return "TIME OVER"
        if "クールダウン" in safe_status:
            return "COOLDOWN"
        if "戦闘中" not in safe_status and hp_pct <= 0:
            return ""

        if hp_pct > 35:
            phase_label = "PHASE 2" if hp_pct <= 70 else "PHASE 1"
        elif hp_pct > 15:
            phase_label = "PHASE 3"
        else:
            phase_label = "LAST STAND"

        if any(keyword in safe_blob for keyword in ("WB激昂", "激昂", "怒りの全体攻撃")) or (
            0 < hp_pct <= 25
        ):
            if phase_label == "LAST STAND":
                return "LAST STAND / ENRAGED"
            return f"{phase_label} / ENRAGED"
        return phase_label

    def _shorten_world_boss_event_text(self, text: str, *, limit: int = 54) -> str:
        safe_text = str(text or "").strip()
        if len(safe_text) <= limit:
            return safe_text
        return safe_text[: max(0, limit - 1)].rstrip() + "…"

    def _build_world_boss_event_state(
        self,
        *,
        title: str,
        status_text: str,
        result_text: str,
        explicit_event_text: str,
        recent_logs: List[str],
    ) -> tuple[str, str]:
        candidates = [
            str(explicit_event_text or "").strip(),
            *(str(log_line).strip() for log_line in reversed(recent_logs) if str(log_line).strip()),
            str(result_text or "").strip(),
            str(status_text or "").strip(),
            str(title or "").strip(),
        ]

        for raw_line in candidates:
            if not raw_line:
                continue
            if "WB全体攻撃" in raw_line or "怒りの全体攻撃" in raw_line:
                return "aoe", self._shorten_world_boss_event_text(raw_line)
            if "会心" in raw_line:
                return "critical", self._shorten_world_boss_event_text(raw_line)
            if "WB撃破:" in raw_line or "戦闘不能" in raw_line or "離脱:" in raw_line:
                return "down", self._shorten_world_boss_event_text(raw_line)
            if "復帰:" in raw_line:
                return "recover", self._shorten_world_boss_event_text(raw_line)
            if "WB激昂" in raw_line or "激昂" in raw_line:
                return "enrage", self._shorten_world_boss_event_text(raw_line)
            if "戦闘開始" in raw_line:
                return "start", self._shorten_world_boss_event_text(raw_line)
            if "WB攻撃:" in raw_line:
                return "attack", self._shorten_world_boss_event_text(raw_line)
            if "総合貢献王 " in raw_line or "MVP " in raw_line or "最多貢献" in raw_line:
                return "ranking", self._shorten_world_boss_event_text(raw_line)
            if "討伐成功" in raw_line:
                return "victory", self._shorten_world_boss_event_text(raw_line)
            if "時間切れ" in raw_line:
                return "timeout", self._shorten_world_boss_event_text(raw_line)
            if "募集中" in raw_line:
                return "recruiting", self._shorten_world_boss_event_text(raw_line)

        return "", ""

    def _resolve_configured_world_boss_visual_paths(self, html_dir: Path, boss_id: str) -> List[Path]:
        safe_boss_id = str(boss_id or "").strip()
        if not safe_boss_id:
            return []

        boss = WORLD_BOSSES.get(safe_boss_id, {})
        raw_visual_file = str(boss.get("visual_file", "") or "").strip()
        if not raw_visual_file:
            return []

        visual_path = Path(raw_visual_file)
        if visual_path.is_absolute() or any(part == ".." for part in visual_path.parts):
            return []

        return [
            html_dir / visual_path,
            html_dir / "assets" / visual_path,
            html_dir / "world_boss" / visual_path,
            html_dir / "assets" / "world_boss" / visual_path,
        ]

    def _resolve_world_boss_visual_url(self, *, boss_id: str = "", boss_name: str = "") -> str:
        html_dir = Path(self.html_path).resolve().parent
        safe_boss_id = str(boss_id or "").strip() or self._guess_world_boss_id(boss_name)
        extensions = (".png", ".webp", ".jpg", ".jpeg")
        candidate_paths = []

        if safe_boss_id:
            candidate_paths.extend(
                self._resolve_configured_world_boss_visual_paths(html_dir, safe_boss_id)
            )
            candidate_paths.extend(
                [
                    html_dir / f"world_boss_visual_{safe_boss_id}{extension}"
                    for extension in extensions
                ]
            )
            candidate_paths.extend(
                [
                    html_dir / f"wb_visual_{safe_boss_id}{extension}"
                    for extension in extensions
                ]
            )
            candidate_paths.extend(
                [
                    html_dir / "world_boss" / f"{safe_boss_id}{extension}"
                    for extension in extensions
                ]
            )
            candidate_paths.extend(
                [
                    html_dir / "assets" / f"world_boss_visual_{safe_boss_id}{extension}"
                    for extension in extensions
                ]
            )
            candidate_paths.extend(
                [
                    html_dir / "assets" / "world_boss" / f"{safe_boss_id}{extension}"
                    for extension in extensions
                ]
            )

        candidate_paths = [
            *candidate_paths,
            html_dir / "world_boss_visual.png",
            html_dir / "world_boss_visual.webp",
            html_dir / "world_boss_visual.jpg",
            html_dir / "world_boss_visual.jpeg",
            html_dir / "wb_visual.png",
            html_dir / "wb_visual.webp",
            html_dir / "assets" / "world_boss_visual.png",
            html_dir / "assets" / "world_boss_visual.webp",
            html_dir / "assets" / "world_boss_visual.jpg",
            html_dir / "assets" / "world_boss_visual.jpeg",
        ]

        for candidate_path in candidate_paths:
            if not candidate_path.is_file():
                continue
            relative_path = candidate_path.relative_to(html_dir).as_posix()
            return quote(relative_path, safe="/:._-%")

        return ""

    def _should_render_world_boss_stage(
        self,
        title: str,
        wb_heading: str,
        result_text: str,
        status_text: str,
    ) -> bool:
        safe_title = str(title or "").strip()
        safe_heading = str(wb_heading or "").strip()
        safe_result = str(result_text or "").strip()
        safe_status = str(status_text or "").strip()

        if safe_heading:
            return True
        if "ワールドボス出現" in safe_title:
            return True
        if "募集中" in safe_status or "戦闘中" in safe_status:
            return True
        return False

    def _build_world_boss_state(self, title: str, entries: List[OverlayEntry]) -> WorldBossOverlayState:
        wb_heading = self._find_first_kv_value(entries, "WB")
        result_text = self._find_first_kv_value(entries, "結果")
        status_text = self._find_first_kv_value(entries, "状態")
        hp_text = self._find_first_kv_value(entries, "HP")
        participants_text = self._find_first_meta_value(entries, "wb_participants_text") or self._find_first_kv_value(
            entries, "参加人数"
        )
        ranking_text = self._find_first_meta_value(entries, "wb_ranking_text") or self._find_first_kv_value(
            entries, "順位"
        )
        phase = self._find_first_meta_value(entries, "wb_phase")
        phase_id = self._find_first_meta_value(entries, "wb_phase_id")
        explicit_boss_id = self._find_first_meta_value(entries, "wb_boss_id")
        explicit_event_kind = self._find_first_meta_value(entries, "wb_event_kind")
        explicit_race_focus_active = self._find_first_meta_value(entries, "wb_race_focus_active")
        explicit_race_text = self._find_first_meta_value(entries, "wb_race_text") or self._find_first_kv_value(
            entries, "総合貢献王争い"
        )
        explicit_event_text = self._find_first_meta_value(entries, "wb_event_text") or self._find_first_kv_value(
            entries, "イベント"
        )
        explicit_show_stage = self._find_first_meta_value(entries, "wb_show_stage")
        explicit_phase_label = self._find_first_kv_value(entries, "フェーズ")
        recent_logs = self._collect_section_values(entries, "直近ログ")
        boss_name, boss_title = self._split_boss_heading(wb_heading)

        if not wb_heading and result_text:
            boss_name = result_text.split(" / ", 1)[0].strip() or "WORLD BOSS"
        if boss_name == "WORLD BOSS" and " / " in title:
            title_tail = title.split(" / ", 1)[1].strip()
            if title_tail and not title_tail.startswith("!wb"):
                boss_name = title_tail

        boss_id = str(explicit_boss_id or "").strip() or self._guess_world_boss_id(boss_name)
        hp_current, hp_max, hp_pct = self._extract_hp_metrics(hp_text)

        phase_blob = " ".join(
            part
            for part in (
                title,
                status_text,
                result_text,
                " ".join(recent_logs),
            )
            if part
        )
        phase_label_map = {
            "idle": "",
            "entry_open": "ENTRY OPEN",
            "phase_1": "PHASE 1",
            "phase_2": "PHASE 2",
            "last_stand": "LAST STAND",
            "boss_down": "BOSS DOWN",
            "time_over": "TIME OVER",
            "cooldown": "COOLDOWN",
        }
        phase_label = (
            explicit_phase_label
            or phase_label_map.get(str(phase_id or "").strip(), "")
            or self._build_world_boss_phase_label(
                title=title,
                status_text=status_text,
                result_text=result_text,
                hp_pct=hp_pct,
                phase_blob=phase_blob,
            )
        )
        if explicit_event_kind or explicit_event_text:
            event_kind = str(explicit_event_kind or "").strip()
            event_text = self._shorten_world_boss_event_text(explicit_event_text)
        else:
            event_kind, event_text = self._build_world_boss_event_state(
                title=title,
                status_text=status_text,
                result_text=result_text,
                explicit_event_text=explicit_event_text,
                recent_logs=recent_logs,
            )

        stage_classes: List[str] = ["wb-stage--idle", self._get_world_boss_theme_class(boss_id)]
        safe_phase = str(phase or "").strip()
        safe_phase_id = str(phase_id or "").strip()
        if safe_phase == "recruiting":
            stage_classes.append("wb-stage--recruiting")
        elif safe_phase == "active":
            stage_classes.append("wb-stage--active")
        elif safe_phase == "cooldown" and ("討伐成功" in result_text or "討伐成功" in phase_blob):
            stage_classes.append("wb-stage--victory")
        elif safe_phase == "cooldown" and ("時間切れ" in result_text or "時間切れ" in phase_blob):
            stage_classes.append("wb-stage--timeout")
        elif safe_phase == "cooldown":
            stage_classes.append("wb-stage--cooldown")
        elif "募集中" in status_text or "ワールドボス出現" in title:
            stage_classes.append("wb-stage--recruiting")
        elif "戦闘中" in status_text:
            stage_classes.append("wb-stage--active")
        elif "討伐成功" in result_text or "討伐成功" in phase_blob:
            stage_classes.append("wb-stage--victory")
        elif "時間切れ" in result_text or "時間切れ" in phase_blob:
            stage_classes.append("wb-stage--timeout")
        elif "クールダウン" in status_text:
            stage_classes.append("wb-stage--cooldown")

        if safe_phase == "active" or "戦闘中" in status_text:
            stage_classes.append("wb-stage--phase-1")
            if safe_phase_id in {"phase_2", "last_stand"} or 0 < hp_pct <= 70:
                stage_classes.append("wb-stage--phase-2")
            if safe_phase_id == "last_stand" or 0 < hp_pct <= 35:
                stage_classes.append("wb-stage--phase-3")
            if safe_phase_id == "last_stand" or 0 < hp_pct <= 15:
                stage_classes.append("wb-stage--last-stand")

        if event_kind in {"attack", "aoe", "start"} or any(
            keyword in phase_blob for keyword in ("WB攻撃", "全体攻撃", "戦闘開始", "スキル発動")
        ):
            stage_classes.append("wb-stage--attack")
        if event_kind == "enrage" or safe_phase_id == "last_stand" or any(
            keyword in phase_blob for keyword in ("激昂", "怒りの全体攻撃")
        ) or (0 < hp_pct <= 25):
            stage_classes.append("wb-stage--enrage")
        if event_kind == "down" or "離脱" in phase_blob:
            stage_classes.append("wb-stage--danger")
        event_class_map = {
            "attack": "wb-stage--impacting",
            "aoe": "wb-stage--aoe",
            "critical": "wb-stage--critical",
            "down": "wb-stage--downed",
            "recover": "wb-stage--recover",
            "enrage": "wb-stage--enrage-flash",
            "start": "wb-stage--start",
            "victory": "wb-stage--victory-flash",
            "timeout": "wb-stage--timeout-flash",
            "ranking": "wb-stage--ranking",
            "recruiting": "wb-stage--recruiting-flash",
        }
        event_class = event_class_map.get(event_kind)
        if event_class:
            stage_classes.append(event_class)
        race_focus_active = str(explicit_race_focus_active or "").strip() not in {"", "0", "false", "False"}
        race_text = str(explicit_race_text or "").strip()
        if race_focus_active and race_text:
            stage_classes.append("wb-stage--race-focus")

        deduped_classes: List[str] = []
        for stage_class in stage_classes:
            if stage_class not in deduped_classes:
                deduped_classes.append(stage_class)

        show_stage = self._should_render_world_boss_stage(
            title,
            wb_heading,
            result_text,
            status_text,
        )
        if explicit_show_stage:
            show_stage = str(explicit_show_stage).strip() not in {"0", "false", "False"}

        return WorldBossOverlayState(
            boss_name=boss_name,
            boss_title=boss_title,
            phase=safe_phase,
            phase_id=safe_phase_id,
            status_text=status_text,
            result_text=result_text,
            hp_text=hp_text,
            hp_current=hp_current,
            hp_max=hp_max,
            hp_pct=hp_pct,
            participants_text=participants_text,
            ranking_text=ranking_text,
            recent_logs=recent_logs[-3:],
            stage_classes=deduped_classes,
            show_stage=show_stage,
            boss_id=boss_id,
            phase_label=phase_label,
            event_text=event_text,
            event_kind=event_kind,
            race_focus_active=race_focus_active,
            race_text=race_text,
            visual_url=(
                self._resolve_world_boss_visual_url(
                    boss_id=boss_id,
                    boss_name=boss_name,
                )
                if show_stage
                else ""
            ),
        )

    def _render_world_boss_visual_panel(
        self,
        state: WorldBossOverlayState,
        *,
        include_hud: bool = True,
    ) -> str:
        if state.visual_url:
            portrait_markup = (
                f"<img class=\"wb-stage__art\" src=\"{escape(state.visual_url)}\" "
                f"alt=\"{escape(state.boss_name)}\" loading=\"eager\">"
            )
        else:
            portrait_markup = (
                "<div class=\"wb-stage__fallback\">"
                "<span class=\"wb-stage__fallback-main\">WB</span>"
                "<span class=\"wb-stage__fallback-sub\">WORLD BOSS</span>"
                "</div>"
            )

        chips: List[str] = []
        if state.status_text:
            chips.append(
                "<span class=\"wb-stage__chip\">"
                f"{escape(state.status_text)}"
                "</span>"
            )
        if state.participants_text:
            chips.append(
                "<span class=\"wb-stage__chip\">"
                f"参加 {escape(state.participants_text)}"
                "</span>"
            )
        if state.race_focus_active and state.race_text:
            chips.append(
                "<span class=\"wb-stage__chip wb-stage__chip--race\">"
                f"争い {escape(state.race_text)}"
                "</span>"
            )
        elif state.ranking_text:
            chips.append(
                "<span class=\"wb-stage__chip\">"
                f"順位 {escape(state.ranking_text)}"
                "</span>"
            )
        if not chips and state.result_text:
            chips.append(
                "<span class=\"wb-stage__chip\">"
                f"{escape(state.result_text)}"
                "</span>"
            )

        hp_markup = ""
        if state.hp_max > 0 and state.hp_text:
            hp_markup = (
                "<div class=\"wb-stage__hp\">"
                "<div class=\"wb-stage__hp-meta\">"
                "<span class=\"wb-stage__hp-label\">HP</span>"
                f"<span class=\"wb-stage__hp-value\">{escape(state.hp_text)}</span>"
                "</div>"
                "<div class=\"wb-stage__hp-track\">"
                f"<div class=\"wb-stage__hp-fill\" style=\"width: {max(0, min(100, state.hp_pct))}%;\"></div>"
                "</div>"
                "</div>"
            )

        log_markup = ""
        if state.recent_logs:
            log_items = "".join(
                f"<li>{escape(log_line)}</li>"
                for log_line in state.recent_logs
                if log_line
            )
            if log_items:
                log_markup = (
                    "<div class=\"wb-stage__logbox\">"
                    "<p class=\"wb-stage__logtitle\">Recent</p>"
                    f"<ul class=\"wb-stage__logs\">{log_items}</ul>"
                    "</div>"
                )

        subtitle = state.boss_title or state.result_text or "チャットで参戦"
        stage_class_parts = ["wb-stage", *state.stage_classes]
        if not include_hud:
            stage_class_parts.append("wb-stage--visual-only")
        stage_class = " ".join(stage_class_parts).strip()
        chips_markup = "".join(chips)
        phase_markup = ""
        if state.phase_label:
            phase_markup = (
                "<div class=\"wb-stage__phase-row\">"
                f"<span class=\"wb-stage__phase\">{escape(state.phase_label)}</span>"
                "</div>"
            )
        event_markup = ""
        if state.event_text:
            event_kind_class = (
                f" wb-stage__event--{escape(state.event_kind)}"
                if state.event_kind
                else ""
            )
            event_markup = (
                f"<div class=\"wb-stage__event{event_kind_class}\">"
                f"{escape(state.event_text)}"
                "</div>"
            )
        hud_markup = ""
        if include_hud:
            hud_markup = (
                "<div class=\"wb-stage__hud\">"
                "<p class=\"wb-stage__eyebrow\">WORLD BOSS</p>"
                f"{phase_markup}"
                f"<h1 class=\"wb-stage__name\">{escape(state.boss_name)}</h1>"
                f"<p class=\"wb-stage__title\">{escape(subtitle)}</p>"
                f"{event_markup}"
                f"{hp_markup}"
                f"<div class=\"wb-stage__chips\">{chips_markup}</div>"
                f"{log_markup}"
                "</div>"
            )

        return (
            f"<aside class=\"{escape(stage_class)}\">"
            "<div class=\"wb-stage__backdrop\"></div>"
            "<div class=\"wb-stage__panel\">"
            "<div class=\"wb-stage__figure-wrap\">"
            "<div class=\"wb-stage__aura\"></div>"
            "<div class=\"wb-stage__impact\"></div>"
            "<div class=\"wb-stage__shadow\"></div>"
            "<div class=\"wb-stage__figure\">"
            "<div class=\"wb-stage__motion\">"
            f"<div class=\"wb-stage__pose\">{portrait_markup}</div>"
            "</div>"
            "</div>"
            "</div>"
            f"{hud_markup}"
            "</div>"
            "</aside>"
        )

    def _render_overlay_panel_markup(
        self,
        safe_title: str,
        safe_timestamp: str,
        joined_lines: str,
        *,
        overlay_class: str = "overlay",
    ) -> str:
        return (
            f"<main class=\"{overlay_class}\">"
            "<header class=\"toolbar\">"
            "<div class=\"title-wrap\">"
            f"<p class=\"eyebrow\">{safe_title}</p>"
            "</div>"
            f"<div class=\"stamp\">{safe_timestamp}</div>"
            "</header>"
            "<section class=\"screen\">"
            f"{joined_lines}"
            "</section>"
            "</main>"
        )

    def _render_blank_markup(self) -> str:
        return "<main class=\"overlay-blank\" aria-hidden=\"true\"></main>"

    def _render_html(
        self,
        title: str,
        timestamp: str,
        entries: List[OverlayEntry],
        *,
        view_mode: str = "combined",
        generated_at_epoch: float | None = None,
    ) -> str:
        joined_lines = self._render_entries_html(entries)
        safe_title = escape(title)
        safe_timestamp = escape(timestamp)
        is_world_boss = self._is_world_boss_overlay(title, entries)
        world_boss_state = self._build_world_boss_state(title, entries) if is_world_boss else None
        generated_epoch = float(generated_at_epoch or datetime.now().timestamp())
        has_wb_stage = bool(
            is_world_boss and world_boss_state and world_boss_state.show_stage
        )

        if view_mode == "wb":
            if is_world_boss and world_boss_state and world_boss_state.show_stage:
                body_class = "body--wb-stage"
                main_markup = (
                    "<main class=\"wb-stage-only\">"
                    f"{self._render_world_boss_visual_panel(world_boss_state, include_hud=False)}"
                    "</main>"
                )
            else:
                body_class = "body--blank"
                main_markup = self._render_blank_markup()
        elif view_mode == "info":
            body_class = ""
            overlay_class = "overlay overlay--wb overlay--wb-full" if is_world_boss else "overlay"
            main_markup = self._render_overlay_panel_markup(
                safe_title,
                safe_timestamp,
                joined_lines,
                overlay_class=overlay_class,
            )
        elif is_world_boss and world_boss_state:
            body_class = "body--wb"
            layout_class = (
                "wb-layout"
                if world_boss_state.show_stage
                else "wb-layout wb-layout--compact"
            )
            overlay_class = (
                "overlay overlay--wb"
                if world_boss_state.show_stage
                else "overlay overlay--wb overlay--wb-full"
            )
            visual_markup = (
                self._render_world_boss_visual_panel(world_boss_state)
                if world_boss_state.show_stage
                else ""
            )
            main_markup = (
                f"<main class=\"{layout_class}\">"
                f"{visual_markup}"
                f"{self._render_overlay_panel_markup(safe_title, safe_timestamp, joined_lines, overlay_class=overlay_class)}"
                "</main>"
            )
        else:
            body_class = ""
            main_markup = self._render_overlay_panel_markup(
                safe_title,
                safe_timestamp,
                joined_lines,
            )

        return f"""<!DOCTYPE html>
<html
  lang="ja"
  data-overlay-view="{escape(view_mode)}"
  data-generated-at-epoch="{generated_epoch:.3f}"
  data-has-wb-stage="{"1" if has_wb_stage else "0"}"
>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>{safe_title}</title>
  <script>
    (() => {{
      const root = document.documentElement;
      const now = Date.now() / 1000;
      const generatedAtEpoch = Number(root.dataset.generatedAtEpoch || "0");
      const hasWbStage = root.dataset.hasWbStage === "1";
      const wbStaleThresholdMs = {int(self.wb_stale_hide_after_sec * 1000)};
      const phase = (duration, offset = 0) => `-${{((now + offset) % duration).toFixed(3)}}s`;

      root.style.setProperty("--wb-delay-backdrop", phase(8.4, 2.6));
      root.style.setProperty("--wb-delay-aura", phase(6.6, 1.8));
      root.style.setProperty("--wb-delay-shadow", phase(6.8, 0.55));
      root.style.setProperty("--wb-delay-float", phase(6.8, 0.0));
      root.style.setProperty("--wb-delay-sway", phase(8.8, 0.9));
      root.style.setProperty("--wb-delay-attack", phase(2.6, 0.24));
      root.style.setProperty("--wb-delay-victory", phase(5.8, 0.36));
      root.style.setProperty("--wb-delay-timeout", phase(6.2, 0.42));

      const syncWbVisibility = () => {{
        if (!hasWbStage || !(generatedAtEpoch > 0)) {{
          root.classList.remove("wb-stage-stale");
          return;
        }}
        const stale = (Date.now() - (generatedAtEpoch * 1000)) > wbStaleThresholdMs;
        root.classList.toggle("wb-stage-stale", stale);
      }};

      syncWbVisibility();
      if (hasWbStage) {{
        window.setInterval(syncWbVisibility, 1000);
      }}
    }})();
  </script>
  <style>
    :root {{
      --ink: #40332a;
      --muted: rgba(76, 60, 48, 0.78);
      --pill: rgba(255, 255, 255, 0.92);
      --pill-strong: rgba(254, 252, 248, 0.96);
      --badge: rgba(62, 45, 36, 0.84);
      --badge-text: #fff8ef;
      --line-no: rgba(160, 108, 60, 0.78);
      --section-bg: rgba(245, 237, 226, 0.94);
      --section-text: #6a4731;
      --border: rgba(129, 92, 58, 0.14);
      --shadow: rgba(26, 19, 14, 0.18);
      --page-pad-x: clamp(10px, 1.8vw, 28px);
      --page-pad-y: clamp(10px, 1.8vh, 28px);
      --safe-width: calc(100vw - (var(--page-pad-x) * 2));
      --safe-height: calc(100vh - (var(--page-pad-y) * 2));
      --overlay-gap: clamp(6px, 0.9vh, 12px);
      --wb-delay-backdrop: 0s;
      --wb-delay-aura: 0s;
      --wb-delay-shadow: 0s;
      --wb-delay-float: 0s;
      --wb-delay-sway: 0s;
      --wb-delay-attack: 0s;
      --wb-delay-victory: 0s;
      --wb-delay-timeout: 0s;
    }}

    * {{
      box-sizing: border-box;
    }}

    html, body {{
      margin: 0;
      width: 100%;
      min-height: 100%;
      background: transparent;
      color: var(--ink);
    }}

    body {{
      min-height: 100vh;
      padding: var(--page-pad-y) var(--page-pad-x);
      display: flex;
      align-items: flex-end;
      justify-content: flex-start;
      overflow: hidden;
      font-family: "BIZ UDPGothic", "Yu Gothic UI", "Hiragino Sans", sans-serif;
    }}

    .body--wb {{
      align-items: stretch;
      justify-content: stretch;
    }}

    .body--wb-stage {{
      padding: 0;
      align-items: stretch;
      justify-content: center;
    }}

    .body--blank {{
      padding: 0;
      align-items: stretch;
      justify-content: stretch;
    }}

    .overlay {{
      width: min(980px, var(--safe-width));
      max-width: 100%;
      max-height: var(--safe-height);
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: flex-start;
      gap: var(--overlay-gap);
      overflow: hidden;
    }}

    .overlay-blank {{
      width: 100%;
      min-height: 100vh;
      background: transparent;
    }}

    .wb-layout {{
      width: 100%;
      min-height: var(--safe-height);
      display: grid;
      grid-template-columns: minmax(280px, 34vw) minmax(420px, 1fr);
      gap: clamp(12px, 2vw, 28px);
      align-items: stretch;
    }}

    html.wb-stage-stale .wb-layout {{
      grid-template-columns: minmax(0, 1fr);
    }}

    .wb-layout--compact {{
      grid-template-columns: minmax(0, 1fr);
    }}

    .overlay--wb {{
      width: min(980px, 100%);
      align-self: flex-end;
      justify-self: start;
    }}

    html.wb-stage-stale .overlay--wb {{
      width: min(980px, var(--safe-width));
      max-width: 100%;
      justify-self: stretch;
    }}

    .overlay--wb-full {{
      width: min(980px, var(--safe-width));
      max-width: 100%;
      justify-self: stretch;
    }}

    .wb-stage-only {{
      width: 100%;
      min-height: 100vh;
      display: flex;
      align-items: stretch;
      justify-content: center;
    }}

    .toolbar {{
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: clamp(6px, 0.8vh, 10px);
      width: 100%;
      flex: 0 0 auto;
    }}

    .title-wrap {{
      min-width: 0;
    }}

    .eyebrow {{
      display: inline-flex;
      max-width: 100%;
      margin: 0;
      padding: clamp(6px, 0.85vh, 8px) clamp(10px, 1vw, 14px);
      border-radius: 999px;
      background: var(--badge);
      color: var(--badge-text);
      font-size: clamp(11px, 1vw, 14px);
      line-height: 1.4;
      font-weight: 700;
      letter-spacing: 0.03em;
      box-shadow: 0 10px 28px var(--shadow);
    }}

    .stamp {{
      flex: 0 0 auto;
      padding: clamp(6px, 0.85vh, 8px) clamp(10px, 1vw, 14px);
      border-radius: 999px;
      background: var(--pill-strong);
      border: 1px solid var(--border);
      font-size: clamp(11px, 0.95vw, 13px);
      color: var(--muted);
      font-family: "Cascadia Code", "IBM Plex Mono", Consolas, monospace;
      box-shadow: 0 10px 28px var(--shadow);
    }}

    .screen {{
      width: 100%;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      gap: var(--overlay-gap);
      min-height: 0;
      overflow: hidden;
    }}

    .section {{
      display: flex;
      align-items: center;
      width: 100%;
      padding: clamp(7px, 0.85vh, 10px) clamp(12px, 1vw, 16px);
      border-radius: 999px;
      background:
        linear-gradient(180deg, rgba(255, 252, 247, 0.97), rgba(247, 239, 230, 0.93)),
        var(--section-bg);
      border: 1px solid rgba(129, 92, 58, 0.18);
      box-shadow: 0 10px 24px var(--shadow);
    }}

    .section--alert {{
      background:
        linear-gradient(180deg, rgba(133, 23, 17, 0.96), rgba(94, 16, 12, 0.93)),
        rgba(133, 23, 17, 0.96);
      border-color: rgba(255, 178, 146, 0.45);
      box-shadow: 0 18px 38px rgba(71, 10, 8, 0.28);
    }}

    .section-text {{
      color: var(--section-text);
      font-size: clamp(11px, 1vw, 14px);
      line-height: 1.4;
      font-weight: 800;
      letter-spacing: 0.04em;
    }}

    .section--alert .section-text {{
      color: #fff8f3;
    }}

    .line {{
      display: grid;
      grid-template-columns: clamp(28px, 4vw, 42px) minmax(0, 1fr);
      gap: clamp(6px, 0.9vw, 10px);
      align-items: start;
      width: 100%;
      padding: clamp(8px, 1vh, 11px) clamp(10px, 1vw, 14px);
      border-radius: clamp(12px, 1.2vw, 16px);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(249, 244, 238, 0.92)),
        var(--pill);
      border: 1px solid var(--border);
      box-shadow: 0 14px 36px var(--shadow);
      backdrop-filter: blur(8px);
    }}

    .line--kv {{
      grid-template-columns: minmax(92px, 180px) minmax(0, 1fr);
      gap: clamp(10px, 1vw, 14px);
      align-items: baseline;
    }}

    .line--alert {{
      background:
        linear-gradient(180deg, rgba(133, 23, 17, 0.96), rgba(94, 16, 12, 0.93)),
        rgba(133, 23, 17, 0.96);
      border-color: rgba(255, 178, 146, 0.45);
      box-shadow: 0 18px 38px rgba(71, 10, 8, 0.28);
    }}

    .line--alert .line-no {{
      color: rgba(255, 213, 190, 0.9);
    }}

    .line--alert .line-text {{
      color: #fff8f3;
      font-weight: 700;
    }}

    .line-no {{
      color: var(--line-no);
      font-size: clamp(10px, 0.8vw, 11px);
      line-height: 1.6;
      text-align: left;
      font-family: "Cascadia Code", "IBM Plex Mono", Consolas, monospace;
      font-weight: 700;
      user-select: none;
    }}

    .kv-label {{
      min-width: 0;
      color: var(--line-no);
      font-size: clamp(10px, 0.92vw, 13px);
      line-height: 1.45;
      font-weight: 800;
      letter-spacing: 0.03em;
    }}

    .kv-value {{
      min-width: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.52;
      font-size: clamp(12px, 1.35vw, 18px);
      font-family: "BIZ UDPGothic", "Yu Gothic UI", "Hiragino Sans", sans-serif;
    }}

    .line-text {{
      min-width: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.52;
      font-size: clamp(12px, 1.45vw, 19px);
      font-family: "BIZ UDPGothic", "Yu Gothic UI", "Hiragino Sans", sans-serif;
    }}

    .line--alert .kv-label,
    .line--alert .kv-value {{
      color: #fff8f3;
    }}

    .spacer {{
      height: clamp(4px, 0.55vh, 8px);
      width: 100%;
      flex: 0 0 auto;
    }}

    .wb-stage {{
      position: relative;
      min-height: min(82vh, 980px);
      display: flex;
      align-items: stretch;
      justify-content: center;
      isolation: isolate;
      --wb-theme-top: rgba(255, 210, 140, 0.54);
      --wb-theme-left: rgba(255, 82, 82, 0.24);
      --wb-theme-right: rgba(32, 104, 255, 0.22);
      --wb-aura-core: rgba(255, 225, 167, 0.88);
      --wb-aura-edge: rgba(255, 139, 79, 0.18);
      --wb-impact-core: rgba(255, 242, 198, 0.42);
      --wb-impact-mid: rgba(255, 189, 111, 0.24);
      --wb-impact-edge: rgba(255, 122, 85, 0.12);
      --wb-bar-a: #f9735c;
      --wb-bar-b: #ffb357;
      --wb-bar-c: #ffe27f;
      --wb-phase-bg: rgba(15, 13, 24, 0.72);
      --wb-phase-border: rgba(255, 231, 197, 0.22);
      --wb-phase-text: rgba(255, 247, 234, 0.98);
      --wb-event-bg: rgba(14, 12, 22, 0.72);
      --wb-event-border: rgba(255, 231, 197, 0.22);
      --wb-event-text: rgba(255, 245, 233, 0.98);
      --wb-panel-glow: rgba(255, 182, 105, 0.24);
    }}

    html.wb-stage-stale .wb-stage {{
      display: none;
    }}

    .wb-stage--visual-only {{
      width: min(100%, 560px);
      min-height: 100vh;
    }}

    .wb-stage.wb-theme--crimson {{
      --wb-theme-top: rgba(255, 173, 120, 0.58);
      --wb-theme-left: rgba(255, 88, 72, 0.30);
      --wb-theme-right: rgba(255, 216, 102, 0.20);
      --wb-aura-core: rgba(255, 214, 150, 0.92);
      --wb-aura-edge: rgba(255, 103, 72, 0.26);
      --wb-impact-core: rgba(255, 244, 194, 0.48);
      --wb-impact-mid: rgba(255, 164, 78, 0.28);
      --wb-impact-edge: rgba(255, 92, 74, 0.16);
      --wb-bar-a: #ff6f4e;
      --wb-bar-b: #ffb03f;
      --wb-bar-c: #ffe182;
      --wb-panel-glow: rgba(255, 131, 74, 0.28);
    }}

    .wb-stage.wb-theme--moon {{
      --wb-theme-top: rgba(182, 225, 255, 0.54);
      --wb-theme-left: rgba(94, 168, 255, 0.22);
      --wb-theme-right: rgba(183, 209, 255, 0.30);
      --wb-aura-core: rgba(214, 240, 255, 0.90);
      --wb-aura-edge: rgba(118, 171, 255, 0.20);
      --wb-impact-core: rgba(225, 247, 255, 0.42);
      --wb-impact-mid: rgba(120, 182, 255, 0.24);
      --wb-impact-edge: rgba(166, 212, 255, 0.16);
      --wb-bar-a: #66a4ff;
      --wb-bar-b: #7fd8ff;
      --wb-bar-c: #d5f3ff;
      --wb-panel-glow: rgba(116, 182, 255, 0.26);
    }}

    .wb-stage.wb-theme--witch {{
      --wb-theme-top: rgba(255, 196, 148, 0.52);
      --wb-theme-left: rgba(198, 88, 68, 0.24);
      --wb-theme-right: rgba(255, 235, 167, 0.22);
      --wb-aura-core: rgba(255, 226, 187, 0.90);
      --wb-aura-edge: rgba(197, 78, 56, 0.22);
      --wb-impact-core: rgba(255, 240, 196, 0.42);
      --wb-impact-mid: rgba(255, 143, 94, 0.26);
      --wb-impact-edge: rgba(98, 12, 10, 0.18);
      --wb-bar-a: #f06b55;
      --wb-bar-b: #ffb26e;
      --wb-bar-c: #ffe2aa;
      --wb-panel-glow: rgba(244, 122, 84, 0.26);
    }}

    .wb-stage.wb-theme--fencer {{
      --wb-theme-top: rgba(255, 236, 178, 0.52);
      --wb-theme-left: rgba(216, 190, 128, 0.22);
      --wb-theme-right: rgba(245, 252, 255, 0.26);
      --wb-aura-core: rgba(255, 244, 211, 0.90);
      --wb-aura-edge: rgba(214, 191, 126, 0.20);
      --wb-impact-core: rgba(255, 251, 219, 0.44);
      --wb-impact-mid: rgba(255, 221, 136, 0.24);
      --wb-impact-edge: rgba(198, 176, 118, 0.14);
      --wb-bar-a: #e1bb66;
      --wb-bar-b: #f7d991;
      --wb-bar-c: #fff1c8;
      --wb-panel-glow: rgba(236, 210, 129, 0.26);
    }}

    .wb-stage--visual-only .wb-stage__panel {{
      width: 100%;
      min-height: 100vh;
      justify-content: center;
      padding: 0;
      background: transparent;
      border: 0;
      box-shadow: none;
      backdrop-filter: none;
      overflow: visible;
    }}

    .wb-stage--visual-only .wb-stage__figure-wrap {{
      position: relative;
      inset: auto;
      flex: 1 1 auto;
      align-items: center;
      min-height: 0;
      overflow: visible;
    }}

    .wb-stage--visual-only .wb-stage__figure {{
      width: min(100%, 560px);
      height: min(94vh, 1040px);
    }}

    .wb-stage--visual-only .wb-stage__backdrop,
    .wb-stage--visual-only .wb-stage__aura,
    .wb-stage--visual-only .wb-stage__impact,
    .wb-stage--visual-only .wb-stage__shadow {{
      display: none;
    }}

    .wb-stage__backdrop {{
      position: absolute;
      inset: 10% 6% 12%;
      border-radius: 42px;
      background:
        radial-gradient(circle at 50% 18%, var(--wb-theme-top), transparent 38%),
        radial-gradient(circle at 28% 66%, var(--wb-theme-left), transparent 42%),
        radial-gradient(circle at 74% 72%, var(--wb-theme-right), transparent 44%);
      filter: blur(34px);
      opacity: 0.82;
      transform: translate3d(0, 0, 0) scale(0.98);
      transform-origin: 50% 55%;
      animation: wb-backdrop-pulse 8.4s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite;
      animation-delay: var(--wb-delay-backdrop);
      will-change: transform, opacity;
      z-index: 0;
      pointer-events: none;
    }}

    .wb-stage__panel {{
      position: relative;
      z-index: 1;
      width: min(100%, 460px);
      min-height: min(80vh, 940px);
      border-radius: clamp(28px, 3vw, 38px);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      padding: clamp(18px, 2.2vh, 26px);
      background:
        linear-gradient(180deg, rgba(21, 20, 29, 0.12), rgba(12, 11, 18, 0.46)),
        linear-gradient(180deg, rgba(255, 248, 238, 0.36), rgba(255, 244, 233, 0.08));
      border: 1px solid rgba(255, 228, 191, 0.28);
      box-shadow:
        0 30px 80px rgba(12, 10, 24, 0.28),
        inset 0 1px 0 rgba(255, 255, 255, 0.36);
      backdrop-filter: blur(10px);
    }}

    .wb-stage__figure-wrap {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      overflow: hidden;
      pointer-events: none;
    }}

    .wb-stage__aura {{
      position: absolute;
      inset: 12% 10% 24%;
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 50%, var(--wb-aura-core), var(--wb-aura-edge) 42%, transparent 72%);
      filter: blur(20px);
      opacity: 0.8;
      transform: translate3d(0, 0, 0) scale(0.98);
      animation: wb-aura-breathe 6.6s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      animation-delay: var(--wb-delay-aura);
      will-change: transform, opacity;
    }}

    .wb-stage__shadow {{
      position: absolute;
      left: 50%;
      bottom: clamp(20px, 3vh, 34px);
      width: min(72%, 280px);
      height: clamp(18px, 3vh, 28px);
      border-radius: 999px;
      background: radial-gradient(circle, rgba(8, 8, 16, 0.42) 0%, rgba(8, 8, 16, 0.18) 54%, transparent 78%);
      filter: blur(10px);
      opacity: 0.34;
      transform: translate3d(-50%, 0, 0) scaleX(1);
      animation: wb-shadow-drift 6.8s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      animation-delay: var(--wb-delay-shadow);
      will-change: transform, opacity;
    }}

    .wb-stage__impact {{
      position: absolute;
      left: 50%;
      bottom: 28%;
      width: min(76%, 320px);
      aspect-ratio: 1;
      border-radius: 50%;
      background:
        radial-gradient(circle, var(--wb-impact-core) 0%, var(--wb-impact-mid) 24%, var(--wb-impact-edge) 42%, transparent 68%);
      filter: blur(8px);
      opacity: 0;
      transform: translate3d(-50%, 0, 0) scale(0.68);
      will-change: transform, opacity;
      mix-blend-mode: screen;
    }}

    .wb-stage__figure {{
      position: relative;
      width: min(100%, 420px);
      height: min(76vh, 860px);
      display: flex;
      align-items: flex-end;
      justify-content: center;
      animation: wb-float 6.8s cubic-bezier(0.42, 0.08, 0.58, 0.94) infinite;
      animation-delay: var(--wb-delay-float);
      will-change: transform;
    }}

    .wb-stage__motion {{
      width: 100%;
      height: 100%;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      transform-origin: 52% 86%;
      animation: wb-idle-sway 8.8s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite;
      animation-delay: var(--wb-delay-sway);
      will-change: transform;
      backface-visibility: hidden;
    }}

    .wb-stage__pose {{
      width: 100%;
      height: 100%;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      transform-origin: 52% 86%;
      will-change: transform;
      backface-visibility: hidden;
    }}

    .wb-stage__art {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      object-position: center bottom;
      filter: none;
      transform: translateZ(0);
      backface-visibility: hidden;
      user-select: none;
    }}

    .wb-stage__fallback {{
      width: clamp(220px, 24vw, 340px);
      aspect-ratio: 3 / 4;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      border-radius: 32px;
      background:
        radial-gradient(circle at 30% 20%, rgba(255, 208, 133, 0.84), transparent 34%),
        radial-gradient(circle at 74% 22%, rgba(255, 87, 87, 0.50), transparent 36%),
        radial-gradient(circle at 50% 76%, rgba(50, 106, 255, 0.54), transparent 38%),
        linear-gradient(180deg, rgba(22, 19, 34, 0.94), rgba(12, 10, 20, 0.98));
      border: 1px solid rgba(255, 232, 198, 0.32);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.16),
        0 28px 58px rgba(10, 8, 20, 0.26);
    }}

    .wb-stage__fallback-main {{
      font-size: clamp(62px, 8vw, 96px);
      font-weight: 900;
      letter-spacing: 0.1em;
      color: rgba(255, 248, 240, 0.96);
      text-shadow: 0 12px 28px rgba(0, 0, 0, 0.26);
    }}

    .wb-stage__fallback-sub {{
      font-size: clamp(12px, 1vw, 14px);
      letter-spacing: 0.16em;
      font-weight: 700;
      color: rgba(255, 227, 185, 0.84);
    }}

    .wb-stage__hud {{
      position: relative;
      z-index: 2;
      width: 100%;
      margin-top: auto;
      padding: clamp(16px, 1.8vh, 22px);
      border-radius: clamp(22px, 2vw, 28px);
      background:
        linear-gradient(180deg, rgba(14, 12, 22, 0.10), rgba(14, 12, 22, 0.68)),
        linear-gradient(180deg, rgba(255, 252, 247, 0.86), rgba(248, 235, 219, 0.60));
      border: 1px solid rgba(255, 235, 204, 0.24);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.24),
        0 18px 44px rgba(12, 10, 24, 0.18);
      backdrop-filter: blur(10px);
    }}

    .wb-stage__eyebrow {{
      margin: 0 0 8px;
      font-size: clamp(11px, 0.95vw, 13px);
      line-height: 1.4;
      font-weight: 900;
      letter-spacing: 0.18em;
      color: rgba(101, 66, 47, 0.88);
    }}

    .wb-stage__phase-row {{
      display: flex;
      justify-content: flex-start;
      margin-bottom: 10px;
    }}

    .wb-stage__phase {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 7px 14px;
      border-radius: 999px;
      background: var(--wb-phase-bg);
      border: 1px solid var(--wb-phase-border);
      color: var(--wb-phase-text);
      font-size: clamp(11px, 0.95vw, 13px);
      line-height: 1.3;
      font-weight: 900;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      box-shadow:
        0 14px 32px rgba(8, 7, 14, 0.24),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
    }}

    .wb-stage__name {{
      margin: 0;
      font-size: clamp(26px, 2.6vw, 40px);
      line-height: 1.05;
      font-weight: 900;
      letter-spacing: 0.02em;
      color: #fffaf4;
      text-shadow: 0 10px 24px rgba(18, 14, 26, 0.28);
    }}

    .wb-stage__title {{
      margin: 10px 0 0;
      font-size: clamp(13px, 1.08vw, 16px);
      line-height: 1.45;
      font-weight: 600;
      color: rgba(255, 235, 208, 0.92);
    }}

    .wb-stage__event {{
      width: fit-content;
      max-width: 100%;
      margin-top: 12px;
      padding: 10px 14px;
      border-radius: 18px;
      background: var(--wb-event-bg);
      border: 1px solid var(--wb-event-border);
      color: var(--wb-event-text);
      font-size: clamp(12px, 1.02vw, 14px);
      line-height: 1.45;
      font-weight: 800;
      box-shadow:
        0 16px 34px rgba(10, 8, 18, 0.28),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
      text-shadow: 0 1px 0 rgba(0, 0, 0, 0.18);
    }}

    .wb-stage__event--critical {{
      background: linear-gradient(180deg, rgba(118, 38, 10, 0.88), rgba(74, 18, 8, 0.92));
      border-color: rgba(255, 214, 136, 0.34);
    }}

    .wb-stage__event--aoe,
    .wb-stage__event--down,
    .wb-stage__event--enrage {{
      background: linear-gradient(180deg, rgba(120, 20, 18, 0.90), rgba(72, 12, 12, 0.94));
      border-color: rgba(255, 178, 146, 0.34);
    }}

    .wb-stage__event--recover {{
      background: linear-gradient(180deg, rgba(20, 94, 64, 0.84), rgba(12, 54, 42, 0.90));
      border-color: rgba(172, 244, 212, 0.28);
    }}

    .wb-stage__event--start,
    .wb-stage__event--recruiting {{
      background: linear-gradient(180deg, rgba(20, 68, 112, 0.84), rgba(14, 34, 62, 0.90));
      border-color: rgba(180, 224, 255, 0.28);
    }}

    .wb-stage__event--victory {{
      background: linear-gradient(180deg, rgba(120, 88, 16, 0.88), rgba(76, 50, 10, 0.92));
      border-color: rgba(255, 222, 146, 0.34);
    }}

    .wb-stage__event--timeout {{
      background: linear-gradient(180deg, rgba(56, 58, 70, 0.90), rgba(28, 30, 40, 0.94));
      border-color: rgba(196, 205, 223, 0.24);
    }}

    .wb-stage__event--ranking {{
      background: linear-gradient(180deg, rgba(90, 68, 22, 0.90), rgba(52, 38, 12, 0.94));
      border-color: rgba(255, 218, 132, 0.30);
    }}

    .wb-stage__hp {{
      margin-top: 16px;
    }}

    .wb-stage__hp-meta {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}

    .wb-stage__hp-label {{
      font-size: clamp(11px, 0.92vw, 13px);
      font-weight: 800;
      letter-spacing: 0.16em;
      color: rgba(255, 229, 194, 0.84);
    }}

    .wb-stage__hp-value {{
      font-size: clamp(12px, 1vw, 14px);
      font-weight: 800;
      color: #fff6ed;
    }}

    .wb-stage__hp-track {{
      position: relative;
      height: 12px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(22, 19, 34, 0.46);
      box-shadow: inset 0 1px 4px rgba(0, 0, 0, 0.24);
    }}

    .wb-stage__hp-fill {{
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--wb-bar-a), var(--wb-bar-b) 52%, var(--wb-bar-c));
      box-shadow:
        0 0 18px var(--wb-panel-glow),
        inset 0 1px 0 rgba(255, 255, 255, 0.24);
    }}

    .wb-stage__chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}

    .wb-stage__chip {{
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(17, 15, 26, 0.42);
      border: 1px solid rgba(255, 231, 197, 0.18);
      color: #fff8ef;
      font-size: clamp(11px, 0.94vw, 13px);
      line-height: 1.35;
      font-weight: 700;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
    }}

    .wb-stage__logbox {{
      margin-top: 16px;
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(15, 13, 22, 0.40);
      border: 1px solid rgba(255, 230, 194, 0.18);
    }}

    .wb-stage__logtitle {{
      margin: 0 0 8px;
      font-size: 11px;
      line-height: 1.3;
      font-weight: 900;
      letter-spacing: 0.18em;
      color: rgba(255, 226, 188, 0.72);
      text-transform: uppercase;
    }}

    .wb-stage__logs {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
      color: rgba(255, 246, 238, 0.88);
      font-size: clamp(12px, 0.96vw, 13px);
      line-height: 1.4;
    }}

    .wb-stage--recruiting .wb-stage__backdrop,
    .wb-stage--recruiting .wb-stage__aura {{
      animation-duration: 5.8s;
    }}

    .wb-stage--recruiting .wb-stage__motion {{
      animation-duration: 7.2s;
    }}

    .wb-stage--attack .wb-stage__pose {{
      animation: wb-attack 2.6s cubic-bezier(0.24, 0.78, 0.22, 1.0) infinite;
      animation-delay: var(--wb-delay-attack);
    }}

    .wb-stage--attack .wb-stage__impact {{
      animation: wb-impact-flash 2.6s cubic-bezier(0.18, 0.88, 0.22, 1.0) infinite;
      animation-delay: var(--wb-delay-attack);
    }}

    .wb-stage--attack .wb-stage__aura {{
      animation-duration: 4.2s;
    }}

    .wb-stage--impacting .wb-stage__impact {{
      animation: wb-impact-flash 1.4s cubic-bezier(0.18, 0.88, 0.22, 1.0) infinite;
    }}

    .wb-stage--phase-2 .wb-stage__panel {{
      box-shadow:
        0 30px 80px rgba(12, 10, 24, 0.28),
        0 0 46px var(--wb-panel-glow),
        inset 0 1px 0 rgba(255, 255, 255, 0.26);
    }}

    .wb-stage--phase-3 .wb-stage__backdrop {{
      filter: blur(38px);
      opacity: 0.9;
    }}

    .wb-stage--last-stand .wb-stage__panel {{
      border-color: rgba(255, 214, 170, 0.34);
      box-shadow:
        0 30px 80px rgba(36, 8, 18, 0.34),
        0 0 58px rgba(255, 122, 76, 0.18),
        inset 0 0 0 1px rgba(255, 214, 170, 0.10);
    }}

    .wb-stage--last-stand .wb-stage__phase {{
      letter-spacing: 0.22em;
    }}

    .wb-stage--race-focus .wb-stage__status {{
      border-color: rgba(255, 221, 154, 0.28);
      box-shadow:
        0 24px 54px rgba(12, 10, 24, 0.22),
        0 0 0 1px rgba(255, 221, 154, 0.08),
        inset 0 1px 0 rgba(255, 250, 224, 0.14);
    }}

    .wb-stage--aoe .wb-stage__impact {{
      animation: wb-impact-aoe 1.8s cubic-bezier(0.2, 0.88, 0.24, 1.0) infinite;
    }}

    .wb-stage--critical .wb-stage__event,
    .wb-stage--victory-flash .wb-stage__event,
    .wb-stage--timeout-flash .wb-stage__event,
    .wb-stage--enrage-flash .wb-stage__event,
    .wb-stage--recruiting-flash .wb-stage__event {{
      animation: wb-banner-flash 1.05s ease-in-out infinite alternate;
    }}

    .wb-stage--downed .wb-stage__panel {{
      box-shadow:
        0 30px 80px rgba(42, 10, 24, 0.34),
        inset 0 1px 0 rgba(255, 215, 193, 0.14);
    }}

    .wb-stage--recover .wb-stage__panel {{
      border-color: rgba(170, 244, 210, 0.26);
      box-shadow:
        0 30px 80px rgba(10, 32, 24, 0.26),
        inset 0 1px 0 rgba(210, 255, 233, 0.14);
    }}

    .wb-stage--enrage .wb-stage__backdrop {{
      background:
        radial-gradient(circle at 50% 18%, rgba(255, 146, 120, 0.56), transparent 36%),
        radial-gradient(circle at 28% 66%, rgba(255, 64, 64, 0.36), transparent 42%),
        radial-gradient(circle at 74% 72%, rgba(144, 34, 34, 0.28), transparent 44%);
      animation-duration: 4.4s;
    }}

    .wb-stage--enrage .wb-stage__aura {{
      background:
        radial-gradient(circle at 50% 50%, rgba(255, 177, 115, 0.86), rgba(255, 90, 90, 0.32) 42%, transparent 72%);
      animation-duration: 4.8s;
    }}

    .wb-stage--victory .wb-stage__figure {{
      animation-duration: 7.4s;
    }}

    .wb-stage--victory .wb-stage__pose {{
      animation: wb-victory 5.8s cubic-bezier(0.34, 0.08, 0.26, 0.98) infinite;
      animation-delay: var(--wb-delay-victory);
    }}

    .wb-stage--victory .wb-stage__backdrop {{
      background:
        radial-gradient(circle at 50% 18%, rgba(255, 226, 122, 0.60), transparent 38%),
        radial-gradient(circle at 24% 68%, rgba(255, 113, 78, 0.28), transparent 44%),
        radial-gradient(circle at 76% 74%, rgba(255, 228, 155, 0.34), transparent 46%);
    }}

    .wb-stage--timeout .wb-stage__pose {{
      animation: wb-timeout 6.2s cubic-bezier(0.38, 0.06, 0.3, 0.98) infinite;
      animation-delay: var(--wb-delay-timeout);
    }}

    .wb-stage--timeout .wb-stage__hud {{
      border-color: rgba(190, 198, 218, 0.22);
    }}

    .wb-stage--danger .wb-stage__panel {{
      box-shadow:
        0 30px 80px rgba(42, 10, 24, 0.34),
        inset 0 1px 0 rgba(255, 255, 255, 0.24);
    }}

    @keyframes wb-float {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); }}
      18% {{ transform: translate3d(0, -4px, 0) scale(1.002); }}
      38% {{ transform: translate3d(0, -11px, 0) scale(1.008); }}
      58% {{ transform: translate3d(0, -7px, 0) scale(1.004); }}
      80% {{ transform: translate3d(0, -2px, 0) scale(1.001); }}
    }}

    @keyframes wb-idle-sway {{
      0%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg); }}
      22% {{ transform: translate3d(-4px, 0, 0) rotate(-0.35deg); }}
      48% {{ transform: translate3d(3px, -2px, 0) rotate(0.28deg); }}
      72% {{ transform: translate3d(1px, 0, 0) rotate(0.12deg); }}
    }}

    @keyframes wb-attack {{
      0%, 12%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg) scale(1); }}
      24% {{ transform: translate3d(-18px, 14px, 0) rotate(-1.8deg) scale(0.986); }}
      38% {{ transform: translate3d(26px, -18px, 0) rotate(1.9deg) scale(1.04); }}
      50% {{ transform: translate3d(42px, -12px, 0) rotate(2.6deg) scale(1.08); }}
      64% {{ transform: translate3d(16px, -6px, 0) rotate(0.8deg) scale(1.028); }}
      80% {{ transform: translate3d(2px, -1px, 0) rotate(0.14deg) scale(1.005); }}
    }}

    @keyframes wb-impact-flash {{
      0%, 20%, 100% {{ opacity: 0; transform: translate3d(-50%, 0, 0) scale(0.68); }}
      34% {{ opacity: 0.14; transform: translate3d(-50%, -3px, 0) scale(0.92); }}
      48% {{ opacity: 0.34; transform: translate3d(-50%, -6px, 0) scale(1.12); }}
      62% {{ opacity: 0.08; transform: translate3d(-50%, -4px, 0) scale(1.22); }}
    }}

    @keyframes wb-impact-aoe {{
      0%, 18%, 100% {{ opacity: 0; transform: translate3d(-50%, 0, 0) scale(0.54); }}
      34% {{ opacity: 0.18; transform: translate3d(-50%, -6px, 0) scale(0.96); }}
      50% {{ opacity: 0.32; transform: translate3d(-50%, -10px, 0) scale(1.32); }}
      72% {{ opacity: 0.04; transform: translate3d(-50%, -6px, 0) scale(1.58); }}
    }}

    @keyframes wb-victory {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); }}
      22% {{ transform: translate3d(0, -6px, 0) scale(1.01); }}
      46% {{ transform: translate3d(0, -16px, 0) scale(1.032); }}
      72% {{ transform: translate3d(0, -8px, 0) scale(1.014); }}
    }}

    @keyframes wb-timeout {{
      0%, 100% {{ transform: translate3d(0, 0, 0) rotate(0deg) scale(1); }}
      32% {{ transform: translate3d(-4px, 6px, 0) rotate(-0.6deg) scale(0.994); }}
      58% {{ transform: translate3d(-8px, 12px, 0) rotate(-1.1deg) scale(0.986); }}
      78% {{ transform: translate3d(-4px, 8px, 0) rotate(-0.5deg) scale(0.99); }}
    }}

    @keyframes wb-aura-breathe {{
      0%, 100% {{ transform: translate3d(0, 0, 0) scale(0.98); opacity: 0.76; }}
      30% {{ transform: translate3d(0, -4px, 0) scale(1.04); opacity: 0.84; }}
      56% {{ transform: translate3d(0, -6px, 0) scale(1.09); opacity: 0.88; }}
      80% {{ transform: translate3d(0, -2px, 0) scale(1.03); opacity: 0.8; }}
    }}

    @keyframes wb-backdrop-pulse {{
      0%, 100% {{ opacity: 0.74; transform: translate3d(0, 0, 0) scale(0.98); }}
      28% {{ opacity: 0.8; transform: translate3d(-6px, -4px, 0) scale(1.005); }}
      58% {{ opacity: 0.86; transform: translate3d(4px, -8px, 0) scale(1.018); }}
      82% {{ opacity: 0.78; transform: translate3d(2px, -2px, 0) scale(0.992); }}
    }}

    @keyframes wb-shadow-drift {{
      0%, 100% {{ transform: translate3d(-50%, 0, 0) scaleX(1) scaleY(1); opacity: 0.34; }}
      38% {{ transform: translate3d(-50%, 0, 0) scaleX(0.94) scaleY(0.9); opacity: 0.26; }}
      64% {{ transform: translate3d(-50%, 0, 0) scaleX(0.97) scaleY(0.94); opacity: 0.29; }}
    }}

    @keyframes wb-banner-flash {{
      0% {{ transform: translate3d(0, 0, 0); box-shadow: 0 14px 32px rgba(8, 7, 14, 0.24); }}
      100% {{ transform: translate3d(0, -2px, 0); box-shadow: 0 18px 40px rgba(255, 164, 91, 0.24); }}
    }}

    @media (max-width: 720px) {{
      .wb-layout {{
        grid-template-columns: 1fr;
        gap: 12px;
      }}

      .wb-stage {{
        min-height: min(52vh, 460px);
      }}

      .wb-stage__panel {{
        width: 100%;
        min-height: min(52vh, 460px);
        padding: 14px;
      }}

      .wb-stage__figure {{
        height: min(50vh, 420px);
      }}

      .wb-stage__name {{
        font-size: 24px;
      }}

      .overlay {{
        width: var(--safe-width);
      }}

      .line {{
        grid-template-columns: 36px minmax(0, 1fr);
        gap: 8px;
        padding: 10px 12px;
        border-radius: 14px;
      }}

      .line--kv {{
        grid-template-columns: minmax(72px, 110px) minmax(0, 1fr);
      }}

      .eyebrow,
      .stamp {{
        font-size: 11px;
      }}

      .kv-value,
      .line-text {{
        font-size: 13px;
      }}
    }}
  </style>
</head>
<body class="{body_class}">
  {main_markup}
</body>
</html>
"""
