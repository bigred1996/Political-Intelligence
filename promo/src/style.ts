// Design tokens mirrored from the live app (web/app/globals.css) so the promo
// matches the product exactly: deep navy + cool off-white + Source Serif display.
import { loadFont as loadSerif } from "@remotion/google-fonts/SourceSerif4";
import { loadFont as loadSans } from "@remotion/google-fonts/PublicSans";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

const serifInfo = loadSerif("normal", { weights: ["400", "600", "700"], subsets: ["latin"] });
const sansInfo = loadSans("normal", { weights: ["400", "500", "600", "700"], subsets: ["latin"] });
const monoInfo = loadMono("normal", { weights: ["400", "500", "600"], subsets: ["latin"] });

export const FONT = {
  serif: serifInfo.fontFamily,
  sans: sansInfo.fontFamily,
  mono: monoInfo.fontFamily,
};

export const C = {
  navy: "#041632",
  navy2: "#081f3d",
  inkSurface: "#1b2b48",
  ink: "#191c1e",
  surface: "#f7f9fb",
  paper: "#ffffff",
  cream: "#f4f1ea",
  creamDim: "#cdd6e6",
  muted: "#44474d",
  faint: "#75777e",
  hairline: "#e2e8f0",
  amber: "#d97706",
  green: "#059669",
  red: "#ba1a1a",
  accent: "#b7c7eb", // accent-on-ink (cool highlight)
  gold: "#c4a86a", // restrained warm hairline for engraved/institutional touches
};
