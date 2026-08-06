"use client";

import { CheckmarkFilled, Renew, WarningAlt } from "@carbon/icons-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

type StreamState = "connecting" | "healthy" | "stale";

export function StreamHealth() {
  const router = useRouter();
  const refreshTimer = useRef<number | null>(null);
  const [, startTransition] = useTransition();
  const [state, setState] = useState<StreamState>("connecting");
  const [lastSync, setLastSync] = useState<Date | null>(null);

  useEffect(() => {
    const stream = new EventSource("/api/stream");
    const scheduleCanonicalRefresh = () => {
      if (refreshTimer.current !== null) return;
      refreshTimer.current = window.setTimeout(() => {
        refreshTimer.current = null;
        startTransition(() => router.refresh());
      }, 250);
    };
    const markHealthy = () => {
      setLastSync(new Date());
      setState("healthy");
    };
    stream.onopen = markHealthy;
    stream.addEventListener("heartbeat", markHealthy);
    stream.addEventListener("event", () => {
      markHealthy();
      scheduleCanonicalRefresh();
    });
    stream.addEventListener("resync", () => {
      markHealthy();
      scheduleCanonicalRefresh();
    });
    stream.onerror = () => setState("stale");
    const staleTimer = window.setInterval(() => {
      setLastSync((value) => {
        if (value && Date.now() - value.getTime() > 45_000) setState("stale");
        return value;
      });
    }, 5_000);
    return () => {
      window.clearInterval(staleTimer);
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      stream.close();
    };
  }, [router]);

  const label =
    state === "healthy"
      ? `Synced ${lastSync ? lastSync.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "now"}`
      : state === "connecting"
        ? "Connecting"
        : "Updates delayed";
  const Icon = state === "healthy" ? CheckmarkFilled : state === "connecting" ? Renew : WarningAlt;

  return (
    <span className="lc-freshness" data-stale={state === "stale"} role="status" aria-live="polite">
      <Icon size={16} aria-hidden />
      {label}
    </span>
  );
}
