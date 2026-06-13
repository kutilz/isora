/**
 * End-to-end encryption of secrets (API keys) to a device's public key.
 *
 * Scheme "ecdh-p256-aesgcm" (v1):
 *   - Device holds a static P-256 (secp256r1) keypair; its public key is shared
 *     as a raw uncompressed point (65 bytes, base64) via the relay.
 *   - Browser generates an ephemeral P-256 keypair, does ECDH, derives an
 *     AES-256-GCM key via HKDF-SHA256, and encrypts the secret.
 *   - The relay only ever sees ciphertext; only the device can decrypt.
 *
 * Matching decryptor: device/utils/crypto_box.py + tools/mock_device.py (Python).
 * Uses the Web Crypto API only (no extra deps). Browser-only.
 */

// Cast helper: TS 5.7's lib.dom narrows BufferSource to ArrayBuffer-backed views;
// our Uint8Arrays are ArrayBuffer-backed at runtime, so this cast is safe.
const bs = (u: Uint8Array): BufferSource => u as unknown as BufferSource;

const SALT = new TextEncoder().encode("auralai-e2e-salt");
const INFO = new TextEncoder().encode("auralai-e2e-v1");

export type SealedSecret = {
  alg: "ecdh-p256-aesgcm";
  epk: string; // base64 raw ephemeral public key
  iv: string; // base64 12-byte nonce
  ct: string; // base64 ciphertext (GCM tag appended)
};

function bufToB64(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function b64ToBuf(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Encrypt one UTF-8 secret string to the device public key (raw point, base64). */
export async function sealToDevice(plaintext: string, devicePubB64: string): Promise<SealedSecret> {
  const subtle = crypto.subtle;
  const devicePub = await subtle.importKey(
    "raw",
    bs(b64ToBuf(devicePubB64)),
    { name: "ECDH", namedCurve: "P-256" },
    false,
    []
  );
  const eph = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const shared = await subtle.deriveBits({ name: "ECDH", public: devicePub }, eph.privateKey, 256);

  const hkdfKey = await subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  const aesKey = await subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: bs(SALT), info: bs(INFO) },
    hkdfKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"]
  );

  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await subtle.encrypt(
    { name: "AES-GCM", iv: bs(iv) },
    aesKey,
    bs(new TextEncoder().encode(plaintext))
  );
  const epkRaw = await subtle.exportKey("raw", eph.publicKey);

  return { alg: "ecdh-p256-aesgcm", epk: bufToB64(epkRaw), iv: bufToB64(iv), ct: bufToB64(ct) };
}
