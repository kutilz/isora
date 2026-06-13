import { t } from "../../lib/i18n";

/**
 * "Lewati ke konten utama" — first focusable element on every page.
 * Hidden off-screen until focused. Tokens.css `.skip-link` styles it.
 */
export function SkipLink() {
  return (
    <a href="#main" className="skip-link">
      {t("common.skip_to_content")}
    </a>
  );
}
