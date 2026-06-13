"""
MVP QR/QRIS scanner untuk MaixCAM (regular) memakai MaixPy + OpenCV.

Jalankan di MaixCAM:
  python qris_scan.py

Catatan:
- Script ini hanya decode QR (payload string). Parsing QRIS/EMVCo bisa ditambah setelah MVP ini stabil.
- Kalau `import cv2` gagal di device, jalankan pipeline decode di companion PC dulu.
"""

from maix import app, camera, display, image, time


def _direction_hint(points, w: int, h: int) -> str:
    """
    points: array 4 titik QR (x,y) dari OpenCV.
    Kembalikan petunjuk arah kasar untuk memusatkan QR.
    """
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except Exception:
        return ""

    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    dx = cx - (w / 2.0)
    dy = cy - (h / 2.0)

    # Deadzone supaya tidak "berisik"
    dead_x = w * 0.12
    dead_y = h * 0.12

    if abs(dx) < dead_x and abs(dy) < dead_y:
        return "TENGAH (tahan)"

    horiz = ""
    vert = ""
    if dx > dead_x:
        horiz = "geser KANAN"
    elif dx < -dead_x:
        horiz = "geser KIRI"

    if dy > dead_y:
        vert = "turun"
    elif dy < -dead_y:
        vert = "naik"

    if horiz and vert:
        return f"{horiz} + {vert}"
    return horiz or vert or ""

def _size_hint(points, w: int, h: int) -> str:
    """
    Estimasi kasar ukuran QR dari bounding box titik.
    Return: "dekatkan", "jauhkan", atau "".
    """
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except Exception:
        return ""

    bw = max(xs) - min(xs)
    bh = max(ys) - min(ys)
    if bw <= 0 or bh <= 0:
        return ""

    area_ratio = (bw * bh) / float(w * h)
    # Ambang empiris untuk guidance: terlalu kecil vs terlalu besar
    if area_ratio < 0.06:
        return "dekatkan"
    if area_ratio > 0.55:
        return "jauhkan"
    return ""


def _maybe_print(msg: str, now_ms: int, last_ms: int, cooldown_ms: int) -> int:
    if not msg:
        return last_ms
    if (now_ms - last_ms) < cooldown_ms:
        return last_ms
    print(msg)
    return now_ms


def main() -> None:
    try:
        import cv2  # type: ignore
    except Exception as e:
        print(f"ERROR: cv2 tidak tersedia: {e}")
        print("Saran: decode QR pakai OpenCV di companion PC dulu.")
        return

    # Untuk performa di MaixCAM: mulai dari resolusi kecil dulu.
    # Kalau QR kecil/jauh, baru naikkan.
    cam_w, cam_h = 320, 240
    cam = camera.Camera(cam_w, cam_h, image.Format.FMT_BGR888)
    cam.skip_frames(20)

    disp = display.Display()
    det = cv2.QRCodeDetector()

    # Throttle decode agar tidak ngelag: deteksi/decode tiap N frame
    decode_every_n = 6
    frame_i = 0

    last_data = ""
    last_qr_print_ms = 0
    last_nav_print_ms = 0
    nav_cooldown_ms = 700

    print("MODE QRIS: aktif")
    print("Instruksi: arahkan kamera ke QR, lalu ikuti petunjuk 'geser' dan 'dekatkan/jauhkan'.")

    while not app.need_exit():
        img = cam.read()
        if img is None:
            time.sleep(0.01)
            continue

        # Convert maix.image.Image -> numpy (tanpa copy untuk performa)
        frame = image.image2cv(img, ensure_bgr=False, copy=False)

        frame_i += 1
        do_decode = (frame_i % decode_every_n) == 0
        data = ""
        points = None

        if do_decode:
            data, points, _ = det.detectAndDecode(frame)

        hint = ""
        size_hint = ""

        if points is not None and len(points) >= 4:
            # points shape biasanya (1,4,2); normalisasi ke list[tuple]
            pts = points
            try:
                if len(points.shape) == 3:
                    pts = points[0]
            except Exception:
                pass

            try:
                pts_i = [(int(p[0]), int(p[1])) for p in pts]
                # Gambar polygon QR
                for i in range(4):
                    x1, y1 = pts_i[i]
                    x2, y2 = pts_i[(i + 1) % 4]
                    img.draw_line(x1, y1, x2, y2, image.Color.from_rgb(0, 255, 0), thickness=2)
                hint = _direction_hint(pts, cam_w, cam_h)
                size_hint = _size_hint(pts, cam_w, cam_h)
            except Exception:
                hint = ""
                size_hint = ""

        if data:
            img.draw_rect(0, 0, cam_w, 24, image.Color.from_rgb(0, 120, 0), thickness=-1)
            img.draw_string(4, 4, "QR TERBACA", image.Color.from_rgb(255, 255, 255), scale=1)

            now_ms = time.ticks_ms()
            if data != last_data or (now_ms - last_qr_print_ms) > 1500:
                last_data = data
                last_qr_print_ms = now_ms
                print("QR:", data)
            last_nav_print_ms = _maybe_print(
                "STATUS: QRIS terbaca. Tahan posisi.",
                now_ms,
                last_nav_print_ms,
                1200,
            )
        else:
            img.draw_rect(0, 0, cam_w, 24, image.Color.from_rgb(20, 20, 30), thickness=-1)
            img.draw_string(4, 4, "Arahkan ke QRIS...", image.Color.from_rgb(255, 255, 255), scale=1)
            now_ms = time.ticks_ms()
            if points is None:
                last_nav_print_ms = _maybe_print(
                    "NAV: cari QR (gerakkan kamera pelan).",
                    now_ms,
                    last_nav_print_ms,
                    nav_cooldown_ms,
                )
            else:
                msg_parts = []
                if hint:
                    msg_parts.append(hint)
                if size_hint:
                    msg_parts.append(size_hint)
                if msg_parts:
                    last_nav_print_ms = _maybe_print(
                        "NAV: " + " | ".join(msg_parts),
                        now_ms,
                        last_nav_print_ms,
                        nav_cooldown_ms,
                    )

        if hint:
            img.draw_rect(0, 26, cam_w, 22, image.Color.from_rgb(20, 20, 30), thickness=-1)
            extra = f" + {size_hint}" if size_hint else ""
            img.draw_string(4, 30, f"Hint: {hint}{extra}", image.Color.from_rgb(255, 220, 0), scale=1)

        disp.show(img)


if __name__ == "__main__":
    main()
