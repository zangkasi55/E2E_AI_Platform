// =============================================================================
// components/pixel/PixelHero.tsx — a parametric 16-bit SVG sprite used by the
// "Credit Memo 16 bit" game tab. One blocky humanoid is drawn from <rect>
// pixels and re-skinned per agent (suit / hair colors) with an optional
// accessory (crown, glasses, helmet+shield, sword+medal). Animation state is
// driven purely by a className so the parent run-player can make every
// character idle-bob, "work" (type), celebrate, or shake when blocked.
// All motion is gated behind prefers-reduced-motion in creditMemo16bit.css.
// =============================================================================
import type { AgentStatus } from "../../types";

export interface HeroPalette {
  skin: string;
  hair: string;
  suit: string;
  suitDark: string;
  shirt: string;
  accent: string;
}

export type HeroAccessory = "crown" | "glasses" | "helmet" | "sword" | "none";

export interface PixelHeroProps {
  palette: HeroPalette;
  accessory?: HeroAccessory;
  state: AgentStatus;
  /** Adds a celebratory raised-arms pose (used when the whole run finishes). */
  cheer?: boolean;
}

const INK = "#10131c";

export function PixelHero({ palette, accessory = "none", state, cheer = false }: PixelHeroProps) {
  const { skin, hair, suit, suitDark, shirt, accent } = palette;
  const cls = ["ph", `ph-${state}`, cheer ? "ph-cheer" : ""].filter(Boolean).join(" ");

  return (
    <svg className={cls} viewBox="0 0 16 18" width="100%" height="100%" shapeRendering="crispEdges" aria-hidden>
      {/* shadow */}
      <ellipse className="ph-shadow" cx="8" cy="17.4" rx="5" ry="0.7" fill="rgba(0,0,0,0.35)" />

      {/* ---- body group (bobs as a whole) ---- */}
      <g className="ph-body">
        {/* legs */}
        <rect className="ph-leg ph-leg-l" x="5" y="13" width="2" height="3" fill={suitDark} />
        <rect className="ph-leg ph-leg-r" x="9" y="13" width="2" height="3" fill={suitDark} />
        <rect x="4" y="16" width="3" height="1" fill={INK} />
        <rect x="9" y="16" width="3" height="1" fill={INK} />

        {/* torso / suit */}
        <rect x="3" y="8" width="10" height="6" fill={suit} />
        <rect x="4" y="8" width="1" height="6" fill={suitDark} />
        <rect x="11" y="8" width="1" height="6" fill={suitDark} />
        {/* shirt + tie */}
        <rect x="6" y="8" width="4" height="4" fill={shirt} />
        <rect x="7" y="8" width="2" height="5" fill={accent} />

        {/* neck */}
        <rect x="6" y="7" width="4" height="1" fill={skin} />

        {/* head */}
        <rect x="4" y="3" width="8" height="4" fill={skin} />
        <rect x="3" y="4" width="1" height="2" fill={skin} />
        <rect x="12" y="4" width="1" height="2" fill={skin} />
        {/* hair */}
        <rect x="3" y="2" width="10" height="2" fill={hair} />
        <rect x="4" y="1" width="8" height="1" fill={hair} />
        <rect x="4" y="3" width="8" height="1" fill={hair} />
        {/* eyes + mouth */}
        <rect className="ph-eye" x="6" y="4" width="1" height="1" fill={INK} />
        <rect className="ph-eye" x="9" y="4" width="1" height="1" fill={INK} />
        <rect x="7" y="6" width="2" height="1" fill="#b46a5a" />

        {/* arms (animate around shoulders) */}
        <g className="ph-arm ph-arm-l">
          <rect x="2" y="8" width="2" height="5" fill={suit} />
          <rect x="2" y="12" width="2" height="1" fill={skin} />
        </g>
        <g className="ph-arm ph-arm-r">
          <rect x="12" y="8" width="2" height="5" fill={suit} />
          <rect x="12" y="12" width="2" height="1" fill={skin} />
        </g>

        {/* ---- accessories ---- */}
        {accessory === "crown" && (
          <g>
            <rect x="3" y="1" width="10" height="1" fill="#ffcf3f" />
            <rect x="4" y="0" width="1" height="1" fill="#ffcf3f" />
            <rect x="7" y="0" width="2" height="1" fill="#ffcf3f" />
            <rect x="11" y="0" width="1" height="1" fill="#ffcf3f" />
            <rect x="7" y="1" width="1" height="1" fill="#ff5c8a" />
          </g>
        )}
        {accessory === "glasses" && (
          <g>
            <rect x="5" y="4" width="2" height="1" fill={INK} />
            <rect x="9" y="4" width="2" height="1" fill={INK} />
            <rect x="7" y="4" width="2" height="1" fill={INK} />
          </g>
        )}
        {accessory === "helmet" && (
          <g>
            <rect x="3" y="1" width="10" height="2" fill="#9fb4c8" />
            <rect x="3" y="3" width="10" height="1" fill="#7d93ab" />
            <rect x="7" y="0" width="2" height="2" fill="#ff5c5c" />
            {/* shield */}
            <g className="ph-shield">
              <rect x="0" y="9" width="3" height="4" fill={accent} />
              <rect x="0" y="13" width="3" height="1" fill={suitDark} />
              <rect x="1" y="10" width="1" height="2" fill="#fff" />
            </g>
          </g>
        )}
        {accessory === "sword" && (
          <g className="ph-sword">
            <rect x="14" y="5" width="1" height="7" fill="#d6deea" />
            <rect x="13" y="12" width="3" height="1" fill="#ffcf3f" />
            <rect x="14" y="13" width="1" height="2" fill="#8a5a2b" />
            {/* medal */}
            <rect x="7" y="10" width="2" height="2" fill="#ffcf3f" />
          </g>
        )}
      </g>

      {/* working sparks */}
      {state === "working" && (
        <g className="ph-sparks">
          <rect x="1" y="5" width="1" height="1" fill="#fff3a8" />
          <rect x="14" y="6" width="1" height="1" fill="#9be7ff" />
          <rect x="13" y="3" width="1" height="1" fill="#fff3a8" />
        </g>
      )}
    </svg>
  );
}
