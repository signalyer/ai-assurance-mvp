// Microsoft 4-square logo, inline SVG (S50 STEP 2).
// Per Microsoft brand guidelines, the four squares are #F25022 (red),
// #7FBA00 (green), #00A4EF (blue), #FFB900 (yellow), no padding between
// quadrants, all four squares equal size. The "Sign in with Microsoft"
// label sits to the right; this component renders the 4-square glyph only.

export function MicrosoftLogo({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 21 21"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}
