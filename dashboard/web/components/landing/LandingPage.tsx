"use client";

import { ScreenRoot } from "@/components/landing";
import ArrivalSequence from "@/components/landing/ArrivalSequence";
import Hero from "@/components/landing/Hero";
import ProofSection from "@/components/landing/ProofSection";
import DonnaPromise from "@/components/landing/DonnaPromise";
import CTA from "@/components/landing/CTA";
import { WhatsAppQRProvider } from "@/lib/landing/WhatsAppQRContext";

// Composition root for the landing page.
// Native document scroll owns navigation between sections. Individual
// sections keep their cinematic composition, but they do not capture wheel
// or touch gestures on this public landing surface.

export default function LandingPage() {
  return (
    <ScreenRoot>
      <WhatsAppQRProvider>
        <main
          id="main-content"
          className="relative bg-paper"
          style={{ minHeight: "100svh", overflowX: "hidden" }}
          aria-label="Main"
        >
          <ArrivalSequence nativeScroll />
          <Hero nativeScroll />
          <ProofSection nativeScroll />
          <DonnaPromise nativeScroll />
          <CTA />
        </main>
      </WhatsAppQRProvider>
    </ScreenRoot>
  );
}
