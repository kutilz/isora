import { t } from "../../lib/i18n";

/** Persistent red banner so operators don't forget they're in admin. */
export function AdminRibbon() {
  return (
    <div class="ribbon" role="status">
      ⚠ {t("admin.ribbon")}
    </div>
  );
}
