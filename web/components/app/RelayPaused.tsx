import AppBar from "@/components/app/AppBar";
import Notice from "@/components/Notice";
import { SettingsGroup, SettingsLink } from "@/components/app/Settings";

/**
 * What every relay-backed screen shows while lib/relay.RELAY_PAUSED is on: why
 * there is nothing to do here, and links that all work right now, so no one is
 * left on a screen that waits for something that will not come.
 */
export function RelayPausedNotice() {
  return (
    <Notice kind="info">
      Fitur tambahan aplikasi (daftar perangkat, menghubungkan, pengaturan jarak jauh) sedang
      tidak aktif. Kacamata I-Sora tetap berfungsi penuh tanpa ponsel: semua fiturnya dijalankan
      dari tombol pada kacamata.
    </Notice>
  );
}

export function RelayPausedLinks() {
  return (
    <SettingsGroup
      title="Yang bisa dicoba sekarang"
      note="Simulasi berjalan sepenuhnya di ponsel — tidak butuh perangkat dan tidak butuh internet setelah terbuka sekali."
    >
      <SettingsLink href="/simulasi" label="Simulasi kamera" sub="Pakai kamera HP seolah-olah sedang memakai I-Sora" />
      <SettingsLink href="/preview" label="Coba suara" sub="Dengarkan chime dan sapaan" />
      <SettingsLink href="/buku" label="Buku panduan" sub="Versi digital dan buku audio" />
      <SettingsLink href="/docs" label="Panduan" sub="Cara pakai, pemasangan, masalah umum" />
      <SettingsLink href="/" label="Tentang I-Sora" />
    </SettingsGroup>
  );
}

/** A whole app screen (with its bar) for routes that have nothing else to show. */
export default function RelayPausedScreen({ title }: { title: string }) {
  return (
    <>
      <AppBar title={title} back="/app" />
      <div className="app-body">
        <RelayPausedNotice />
        <RelayPausedLinks />
      </div>
    </>
  );
}
