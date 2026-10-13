import type { PromoProps } from "./types";

// Studio preview only; production props always come from the Python side.
export const SAMPLE: PromoProps = {
  fps: 30,
  width: 1080,
  height: 1920,
  duration: 36,
  beat: 0.5,
  palette: { bg: "#0B0B0C", ink: "#FFFFFF", accent: "#FFC400", brand: "#F5A800", muted: "#A3A3A8" },
  scenes: [
    { type: "hook", at: [0, 6], lines: ["Ishga?", "Uchrashuvga?"], lead: "Qayerga bo'lmasin —", punch: "Kechikmang." },
    { type: "logo", at: [6, 10], name: "ANGREN TAXI", tagline: "Shahringizning o'z taksisi", pattern: "checker" },
    { type: "feature", at: [10, 16], index: "01", label: "Tezkor", title: "Tez yetib kelamiz", accent: "Tez", subtitle: "Buyurtma bering — mashina yo'lda.", icon: "bolt" },
    { type: "list", at: [16, 22], title: "Qulay narx", accent: "narx", items: ["Hamyonbop tariflar", "Toza salon", "Xushmuomala haydovchi"] },
    { type: "stat", at: [22, 26], value: 12000, suffix: "+", label: "mamnun yo'lovchi" },
    { type: "cta", at: [26, 36], name: "ANGREN TAXI", tagline: "Yo'lingiz — ishonchli qo'llarda", accent: "ishonchli qo'llarda", button: "Hoziroq buyurtma bering", contact: "" },
  ],
};
