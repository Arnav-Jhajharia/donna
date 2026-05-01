// Ambient declarations for landing-page deps that are listed in
// package.json but not installed in this checkout. These types only
// describe the surface used by the landing components; the real
// types ship with the package once `npm install` runs.
declare module "react-qr-code" {
  import type { CSSProperties } from "react";

  interface QRCodeProps {
    value: string;
    size?: number;
    bgColor?: string;
    fgColor?: string;
    level?: "L" | "M" | "Q" | "H";
    title?: string;
    style?: CSSProperties;
    viewBox?: string;
  }

  const QRCode: React.FC<QRCodeProps>;
  export default QRCode;
}
