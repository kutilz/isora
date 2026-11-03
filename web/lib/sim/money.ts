/**
 * Banknote logic, ported from device/utils/money.py and the money_* values in
 * device/config.py. Retune the device, retune this.
 */

/** config: money_conf_threshold. */
export const MONEY_CONF_THRESHOLD = 0.5;
/** config: iou_threshold. */
export const MONEY_IOU_THRESHOLD = 0.45;
/** config: money_min_streak, money_gone_s, money_repeat_gap_s. */
export const MONEY_MIN_STREAK = 3;
export const MONEY_GONE_S = 1.5;
export const MONEY_REPEAT_GAP_S = 4.0;

/** Class order of the trained model, as in tools/money_model/uang_yolo26n.mud. */
export const MONEY_LABELS = ["UANG_100K", "UANG_1K", "UANG_2K", "Uang_5k", "UANG_10K", "Uang_20k", "Uang_50k"];

/** nominal_from_label for the spellings this model uses. */
export function nominalFromLabel(label: string): number | null {
  const m = /(\d+)\s*k\b/i.exec(label);
  return m ? Number(m[1]) * 1000 : null;
}

const SATUAN = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"];

/** terbilang, up to the range a banknote can reach. */
export function terbilang(n: number): string {
  const join = (head: string, rest: number) => (rest ? `${head} ${terbilang(rest)}` : head);
  if (n < 12) return SATUAN[n];
  if (n < 20) return `${SATUAN[n - 10]} belas`;
  if (n < 100) return join(`${SATUAN[Math.floor(n / 10)]} puluh`, n % 10);
  if (n < 200) return join("seratus", n - 100);
  if (n < 1000) return join(`${SATUAN[Math.floor(n / 100)]} ratus`, n % 100);
  if (n < 2000) return join("seribu", n - 1000);
  return join(`${terbilang(Math.floor(n / 1000))} ribu`, n % 1000);
}

/** What the device says for a banknote: "lima puluh ribu rupiah". */
export function spokenNominal(value: number): string {
  return `${terbilang(value)} rupiah`;
}

/**
 * Port of utils/money.PresenceTracker. A value becomes present after min_streak
 * sightings in a row and stops being present after gone_s unseen, so each note
 * is said once when it arrives, not once per frame.
 */
export class PresenceTracker {
  private streak = new Map<number, number>();
  private lastSeen = new Map<number, number>();
  private presentSet = new Set<number>();
  private pending: number[] = [];
  private saidAt = new Map<number, number>();

  reset() {
    this.streak.clear();
    this.lastSeen.clear();
    this.presentSet.clear();
    this.pending = [];
    this.saidAt.clear();
  }

  update(seen: Iterable<number>, now: number) {
    const seenSet = new Set(seen);
    for (const key of seenSet) {
      const count = (this.streak.get(key) ?? 0) + 1;
      this.streak.set(key, count);
      this.lastSeen.set(key, now);
      if (!this.presentSet.has(key) && count >= MONEY_MIN_STREAK) {
        this.presentSet.add(key);
        if (!this.pending.includes(key)) this.pending.push(key);
      }
    }
    // One dropped frame of a note being held still does not count as putting it down.
    for (const key of [...this.streak.keys()]) {
      if (seenSet.has(key)) continue;
      if (!this.presentSet.has(key)) {
        this.streak.delete(key);
      } else if (now - (this.lastSeen.get(key) ?? now) >= MONEY_GONE_S) {
        this.presentSet.delete(key);
        this.streak.delete(key);
        this.pending = this.pending.filter((k) => k !== key);
      }
    }
  }

  /** Arrivals not yet said (respecting the repeat gap); marks them said. */
  take(now: number): number[] {
    const out: number[] = [];
    for (const key of [...this.pending]) {
      if (now - (this.saidAt.get(key) ?? -Infinity) < MONEY_REPEAT_GAP_S) continue;
      this.pending = this.pending.filter((k) => k !== key);
      this.saidAt.set(key, now);
      out.push(key);
    }
    return out;
  }

  get present(): number[] {
    return [...this.presentSet];
  }
}
