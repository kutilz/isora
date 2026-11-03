import Link from "next/link";

export const metadata = {
  title: "Tidak ada koneksi — I-Sora",
  description: "Halaman ini butuh internet. Simulasi kamera tetap bisa dipakai offline.",
};

export default function OfflinePage() {
  return (
    <div className="container section" style={{ maxWidth: 560 }}>
      <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Tidak ada koneksi</h1>
      <p className="sub">
        Halaman yang kamu buka butuh internet. Status dan pengaturan perangkat akan muncul
        lagi begitu ponselmu tersambung.
      </p>
      <div className="card">
        <p style={{ margin: 0 }}>
          <strong>Yang tetap bisa dipakai sekarang:</strong>
        </p>
        <p style={{ margin: "var(--s-3) 0 var(--s-4)", color: "var(--ink-2)" }}>
          Simulasi kamera berjalan sepenuhnya di ponsel — deteksi objek, chime arah, dan
          suara Indonesia tidak butuh server sama sekali.
        </p>
        <Link href="/simulasi" className="btn btn--primary btn--lg">
          Buka simulasi kamera
        </Link>
      </div>
    </div>
  );
}
