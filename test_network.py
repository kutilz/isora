# Jalankan script ini di MaixCam via MaixVision untuk diagnosa jaringan
# Ganti HOST_IP jika berbeda
HOST_IP   = "192.168.1.78"
HOST_PORT = 5000
import socket, time

print(f"=== TEST KONEKSI KE {HOST_IP}:{HOST_PORT} ===\n")

# Test 1: TCP socket langsung
print("1. Test TCP socket...")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
t0 = time.time()
result = s.connect_ex((HOST_IP, HOST_PORT))
ms = int((time.time() - t0) * 1000)
s.close()
if result == 0:
    print(f"   BERHASIL ({ms}ms) - Server bisa dicapai!")
elif result == 111:
    print(f"   GAGAL: Connection REFUSED (server tidak jalan di {HOST_IP}:{HOST_PORT})")
elif result == 110:
    print(f"   GAGAL: Connection TIMEOUT ({ms}ms) - Router memblokir (AP Isolation?)")
else:
    print(f"   GAGAL: errno={result} ({ms}ms)")

# Test 2: HTTP GET
print("\n2. Test HTTP GET /api/status...")
try:
    import urequests as requests  # MaixPy pakai urequests
except ImportError:
    try:
        import requests
    except ImportError:
        requests = None
        print("   requests module tidak ada!")

if requests:
    try:
        t0 = time.time()
        r = requests.get(f"http://{HOST_IP}:{HOST_PORT}/api/status", timeout=5)
        ms = int((time.time() - t0) * 1000)
        print(f"   BERHASIL! Status: {r.status_code} ({ms}ms)")
        print(f"   Response: {r.text[:100]}")
    except Exception as e:
        print(f"   GAGAL: {type(e).__name__}: {e}")

# Test 3: Cek default gateway
print("\n3. Test gateway (router)...")
gw = "192.168.1.1"
s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s2.settimeout(3)
r2 = s2.connect_ex((gw, 80))
s2.close()
print(f"   Gateway {gw}:80 -> {'BISA DICAPAI' if r2 == 0 else f'errno={r2}'}")

print("\n=== SELESAI ===")
print("Kirimkan output di atas ke developer")
