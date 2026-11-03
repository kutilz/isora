/**
 * When "Jelaskan sekitar" may spend the shared OpenAI key, every day, in WIB.
 * The server enforces this (app/api/describe/route.ts); the page only words it.
 */
export const DESCRIBE_OPEN_MIN = 12 * 60 + 50;
export const DESCRIBE_CLOSE_MIN = 15 * 60 + 30;
export const DESCRIBE_HOURS_LABEL = "12.50–15.30 WIB";

/** Minutes since midnight in Jakarta, whatever zone the machine runs in. */
export function jakartaMinutes(now: Date = new Date()): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return get("hour") * 60 + get("minute");
}

export function describeIsOpen(now: Date = new Date()): boolean {
  const minutes = jakartaMinutes(now);
  return minutes >= DESCRIBE_OPEN_MIN && minutes < DESCRIBE_CLOSE_MIN;
}
