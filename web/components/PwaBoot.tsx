"use client";

import { useEffect } from "react";
import { initPwa } from "@/lib/pwa";

/** Registers the service worker and starts listening for the install prompt. */
export default function PwaBoot() {
  useEffect(() => {
    initPwa();
  }, []);
  return null;
}
