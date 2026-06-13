# Accessibility checklist — WCAG 2.1 AA

> Companion + Admin + Guide harus lulus semua item di bawah sebelum dirilis ke
> pendamping pertama.

## 1. Perceivable

- [ ] Semua teks ≥ 4.5:1 contrast vs background (token sudah dipilih sesuai)
- [ ] Teks besar (≥ 18px bold atau 24px reg) ≥ 3:1
- [ ] Non-text UI (icon, border, focus ring) ≥ 3:1
- [ ] Setiap `<img>` punya `alt` yang deskriptif (atau `alt=""` kalau dekoratif)
- [ ] SVG informatif punya `<title>` atau `aria-label`
- [ ] Tidak ada info disampaikan **hanya** dengan warna (selalu pasangkan
      dengan ikon, badge text, atau pattern)
- [ ] Tidak ada teks di gambar (kecuali logo)
- [ ] Audio player punya transcript / caption (chime player di /guide cukup
      dengan label visual ChimeShape)

## 2. Operable

- [ ] **Semua interaksi keyboard-accessible** (tab, enter, space, arrows)
- [ ] Setiap fokus visible dengan ring 3px (`--focus`)
- [ ] Skip-link "Lewati ke konten utama" di top
- [ ] Hit target ≥ 48×48px (lebih ketat dari WCAG AA = 44px)
- [ ] Tidak ada keyboard trap (modal punya Esc + restore focus)
- [ ] Keyboard shortcut tidak conflict dengan screen reader:
      - `1/2/3` ganti mode — hanya aktif saat tidak ada input focus
      - `+/-` volume — hanya saat tidak ada input
      - `?` buka bantuan
- [ ] Tidak ada timing-required interaction (tidak ada countdown otomatis
      kecuali user bisa pause/extend)
- [ ] Tidak ada konten yang flash >3× per detik
- [ ] `prefers-reduced-motion` dipatuhi (sudah di tokens.css)

## 3. Understandable

- [ ] `<html lang="id">` di root
- [ ] Bahasa Indonesia sederhana, hindari istilah teknis (atau berikan
      tooltip)
- [ ] Form error message: jelaskan **apa** salahnya + **cara perbaiki**
- [ ] Form field punya `<label>` ter-asosiasi (`for=`/`id=` atau wrap)
- [ ] Field wajib ditandai jelas (asterisk + `aria-required`)
- [ ] Tidak ada konteks yang berubah saat input gain focus (kebijakan
      "no-change-on-focus")
- [ ] Tombol vs link konsisten: link = navigasi, tombol = aksi

## 4. Robust

- [ ] HTML valid (test dengan W3C validator)
- [ ] Setiap `id` unik
- [ ] Tidak ada nested interactive (button di dalam button, link di dalam link)
- [ ] ARIA pattern dipakai dengan benar:
      - Tabs: `role="tablist"`, `aria-selected`, `aria-controls`
      - Radio group: `role="radiogroup"`, `role="radio"`, `aria-checked`
      - Modal: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`
      - Live region: `aria-live="polite"` (status), `assertive` (error)
- [ ] `aria-label` hanya saat tidak ada visual label
- [ ] Tested di NVDA + VoiceOver minimal sekali

## 5. Specific to AuralAI

- [ ] Last-caption box di LiveView pakai `aria-live="polite"` — SR
      mengumumkan caption baru
- [ ] Status banner pakai `aria-live="polite"` — perubahan koneksi diumumkan
- [ ] Mode change melemparkan announcement: "Mode berganti ke Deskripsi"
- [ ] Setup wizard step transitions di-announce
- [ ] Filter chip aktivitas: `aria-pressed`
- [ ] Activity feed item: `<time datetime="...">` untuk timestamp

## 6. Testing

```bash
# Setelah implementasi:
1. axe DevTools — 0 violations
2. WAVE — 0 errors
3. Keyboard-only walkthrough — semua tugas bisa selesai tanpa mouse
4. Screen reader walkthrough (NVDA atau VoiceOver) — semua info dapat dibaca
5. Browser zoom 200% — tidak ada teks terpotong, tidak ada horizontal scroll
6. Browser zoom 400% — content reflow ke single column dengan baik
```
