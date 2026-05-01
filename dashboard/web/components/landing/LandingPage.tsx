"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ScreenRoot } from "@/components/landing";
import ArrivalSequence from "@/components/landing/ArrivalSequence";
import Hero from "@/components/landing/Hero";
import ProofSection from "@/components/landing/ProofSection";
import DonnaPromise from "@/components/landing/DonnaPromise";
import CTA from "@/components/landing/CTA";
import { WhatsAppQRProvider } from "@/lib/landing/WhatsAppQRContext";

// Composition root for the landing page.
//
// The entire experience is a phase state machine — no native page scroll,
// ever. Each phase is a fixed 100svh overlay. Gestures are consumed by
// whichever phase is active and advance the state; they never scroll the
// document. That gives us:
//
//   . One scroll = one beat, consistently, across arrival -> hero -> proof.
//   . No "hero skipped" because the hero isn't something you scroll past
//     it's a phase you step into and then step out of with one more gesture.
//   . "No back scroll" is free: there is no scroll to go back on.
//
// Phase flow:
//   arrival  -> hero    (final-line scroll on ArrivalSequence)
//   hero     -> proof   (one scroll on Hero)
//   proof    -> promise (one scroll past state 9)
//   promise  -> cta     (one scroll past the letter's unroll)
//   cta      -> (terminal — the action is tapping the button)
type Phase = "arrival" | "hero" | "proof" | "promise" | "cta";

export default function LandingPage() {
  const [phase, setPhase] = useState<Phase>("arrival");

  // Lock the document. No scrollbar, no native scroll, no back-scroll.
  useEffect(() => {
    const prevBody = document.body.style.overflow;
    const prevHtml = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevBody;
      document.documentElement.style.overflow = prevHtml;
    };
  }, []);

  return (
    <ScreenRoot>
      <WhatsAppQRProvider>
        <main
          id="main-content"
          className="relative bg-paper"
          style={{ height: "100svh", overflow: "hidden" }}
          aria-label="Main"
        >
          <AnimatePresence mode="sync">
            {phase === "arrival" && (
              <motion.div
                key="arrival"
                className="absolute inset-0 z-30"
                initial={false}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.5, ease: [0.2, 0, 0, 1] }}
              >
                <ArrivalSequence onComplete={() => setPhase("hero")} />
              </motion.div>
            )}

            {phase === "hero" && (
              <motion.div
                key="hero"
                className="absolute inset-0 z-20"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.5, ease: [0.2, 0, 0, 1] }}
              >
                <Hero onAdvance={() => setPhase("proof")} />
              </motion.div>
            )}

            {phase === "proof" && (
              <motion.div
                key="proof"
                className="absolute inset-0 z-10"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.5, ease: [0.2, 0, 0, 1] }}
              >
                <ProofSection onComplete={() => setPhase("promise")} />
              </motion.div>
            )}

            {phase === "promise" && (
              <motion.div
                key="promise"
                className="absolute inset-0 z-10"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.5, ease: [0.2, 0, 0, 1] }}
              >
                <DonnaPromise onAdvance={() => setPhase("cta")} />
              </motion.div>
            )}

            {phase === "cta" && (
              <motion.div
                key="cta"
                className="absolute inset-0 z-10"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5, ease: [0.2, 0, 0, 1] }}
              >
                <CTA />
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </WhatsAppQRProvider>
    </ScreenRoot>
  );
}
