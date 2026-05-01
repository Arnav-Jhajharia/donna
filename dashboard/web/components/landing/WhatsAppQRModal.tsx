"use client";

/**
 * WhatsAppQRModal — desktop conversion path, fully inside the design
 * system. Type roles, hairlines, the one allowed shadow token, no inline
 * font-sizes, no raw hex (the QR's two colors are imported from the brand
 * core palette via const, not freelanced).
 *
 * Composition:
 *   ┌──────────────────────────────────────────┐
 *   │  ✕                                        │
 *   │                                           │
 *   │  Heading (h2) — italic-accent            │
 *   │  body sub-line — muted                   │
 *   │                                           │
 *   │  ┌──── QR (anchor + hairline) ────┐      │
 *   │  │                                 │      │
 *   │  └─────────────────────────────────┘      │
 *   │                                           │
 *   │  LABEL · scan or click                    │
 *   └──────────────────────────────────────────┘
 *
 * Italic usage: the h2 italic on the *whole* line is one of the three
 * approved italic contexts (italic-accent-heading) since the entire
 * heading is the editorial display moment.
 */

import { useEffect, useRef } from "react";
import QRCode from "react-qr-code";
import { Label } from "@/components/landing";

// QR colors — pulled directly from the brand core palette tokens.
// `--color-paper` and `--color-rust` are CSS vars at runtime; QR libs need
// concrete strings, so we hard-code the same hex values that tokens.css /
// design-system/tokens.json declare for these roles. If those tokens ever
// change, these change with them. The QR uses the rust accent so the modal
// itself carries one rust moment (matching the rest of the brand language).
// eslint-disable-next-line donna/no-raw-hex
const QR_BG = "#FBF7F5"; // = --color-paper
// eslint-disable-next-line donna/no-raw-hex
const QR_FG = "#7B5544"; // = --color-rust

type Props = {
  open: boolean;
  href: string;
  onClose: () => void;
};

export default function WhatsAppQRModal({ open, href, onClose }: Props) {
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    if (typeof window === "undefined") return;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);

    const t = window.setTimeout(() => closeBtnRef.current?.focus(), 30);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Scan to open WhatsApp on your phone"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[100] flex items-center justify-center px-4 sm:px-8"
      style={{
        // Editorial scrim — ink at 50%, lower than the modal's own surface.
        // Slight blur sells the depth without competing with the paper card.
        backgroundColor: "rgba(30, 26, 24, 0.5)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
    >
      <div
        className="relative bg-surface rounded-lg shadow-modal w-full"
        style={{
          maxWidth: "440px",
          padding: "var(--space-7)",
          // Subtle hairline so the paper sits inside the scrim with a
          // crisp edge, not floating.
          border: "1px solid var(--ink-300)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close — text-small ink that warms to rust on hover. */}
        <button
          ref={closeBtnRef}
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="absolute font-sans text-small text-ink hover:text-rust focus:outline-none focus:ring-focus focus:ring-rust focus:ring-offset-2 focus:ring-offset-paper rounded-sm"
          style={{
            top: "var(--space-3)",
            right: "var(--space-4)",
            lineHeight: 1,
            padding: "var(--space-1) var(--space-2)",
          }}
        >
          {"✕"}
        </button>

        {/* Headline — h2 role, italic accent across the full line. */}
        <h2 className="font-serif text-h2 text-ink m-0">
          <em className="italic-accent-heading font-medium">
            Scan to text her.
          </em>
        </h2>

        {/* Sub-line — body role, muted secondary text. */}
        <p
          className="font-sans text-body m-0"
          style={{
            marginTop: "var(--space-3)",
            color: "var(--color-muted)",
          }}
        >
          Donna lives on WhatsApp. Point your phone camera at the code.
        </p>

        {/* QR — real anchor (clickable as fallback), hairline frame, paper inset. */}
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Open WhatsApp to message Donna"
          className="block rounded-md focus:outline-none focus:ring-focus focus:ring-rust focus:ring-offset-2 focus:ring-offset-paper"
          style={{
            marginTop: "var(--space-6)",
            backgroundColor: "var(--color-paper)",
            padding: "var(--space-5)",
            border: "1px solid var(--ink-300)",
          }}
        >
          <QRCode
            value={href}
            size={256}
            bgColor={QR_BG}
            fgColor={QR_FG}
            level="M"
            style={{
              width: "100%",
              height: "auto",
              display: "block",
            }}
          />
        </a>

        {/* Caption — uppercase rust label, brand-canonical small hint. */}
        <div
          style={{
            marginTop: "var(--space-5)",
            textAlign: "center",
          }}
        >
          <Label>Click to open here · or scan from phone</Label>
        </div>
      </div>
    </div>
  );
}
