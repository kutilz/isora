/**
 * I-Sora "beacon / penuntun" mark — a glowing core with rings radiating out.
 * Mirrors the logo in brand/isora-brand-identity.html. Amber core on any bg.
 */
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="img"
      aria-label="Logo I-Sora"
      style={{ flex: "none" }}
    >
      <circle cx="50" cy="50" r="40" fill="none" stroke="#F4A23B" strokeWidth="3" opacity="0.25" />
      <circle cx="50" cy="50" r="26" fill="none" stroke="#F4A23B" strokeWidth="3.4" opacity="0.55" />
      <circle cx="50" cy="50" r="13" fill="none" stroke="#F4A23B" strokeWidth="3.6" opacity="0.9" />
      <circle cx="50" cy="50" r="6" fill="#F4A23B" />
    </svg>
  );
}
