"use client";

import { Pause, PlayFilledAlt, Send, Stop } from "@carbon/icons-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import type { EventItem } from "@/lib/limina/types";

type ConnectionState = "connecting" | "live" | "reconnecting" | "closed";

type LiveMonitorProps = {
  slug: string;
  initialCursor: number;
  initialEvents: EventItem[];
  canSteer: boolean;
  allowedActions: string[];
};

type LiveFrame =
  | { type: "event"; value: EventItem }
  | { type: "snapshot"; value: unknown }
  | { type: "delivery"; value: string }
  | { type: "state"; value: unknown }
  | { type: "error"; value: { message?: string } };

export function LiveMonitor({
  slug,
  initialCursor,
  initialEvents,
  canSteer,
  allowedActions,
}: LiveMonitorProps) {
  const socket = useRef<WebSocket | null>(null);
  const cursor = useRef(initialCursor);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState(initialEvents.slice(-100));
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(async () => {
    setConnection((current) => (current === "connecting" ? current : "reconnecting"));
    setError(null);
    try {
      const ticketResponse = await fetch(`/api/projects/${encodeURIComponent(slug)}/live-ticket`, {
        method: "POST",
        headers: { accept: "application/json" },
      });
      if (!ticketResponse.ok) throw new Error("Live authorization was not available.");
      const ticket = (await ticketResponse.json()) as { ticket: string };
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${scheme}//${window.location.host}/v2/projects/${encodeURIComponent(slug)}/live?after=${cursor.current}`;
      const nextSocket = new WebSocket(url, ["limina.v2", `limina.ticket.${ticket.ticket}`]);
      socket.current = nextSocket;
      nextSocket.onopen = () => setConnection("live");
      nextSocket.onmessage = (message) => {
        const frame = JSON.parse(String(message.data)) as LiveFrame;
        if (frame.type === "event") {
          if (frame.value.sequence <= cursor.current) return;
          cursor.current = frame.value.sequence;
          setEvents((current) => [...current, frame.value].slice(-100));
        } else if (frame.type === "error") {
          setError(frame.value.message ?? "The live operation was rejected.");
        }
      };
      nextSocket.onerror = () => setError("The live connection encountered an error.");
      nextSocket.onclose = () => {
        if (socket.current === nextSocket) setConnection("closed");
      };
    } catch (reason) {
      setConnection("closed");
      setError(reason instanceof Error ? reason.message : "Live mode could not connect.");
    }
  }, [slug]);

  useEffect(() => {
    void connect();
    return () => {
      socket.current?.close();
      socket.current = null;
    };
  }, [connect]);

  function submitGuidance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = String(form.get("body") ?? "").trim();
    const kind = String(form.get("kind") ?? "STEER");
    if (!body || socket.current?.readyState !== WebSocket.OPEN) return;
    socket.current.send(JSON.stringify({ type: "steer", kind, body }));
    event.currentTarget.reset();
  }

  function sendAction(action: string) {
    if (socket.current?.readyState !== WebSocket.OPEN) return;
    socket.current.send(JSON.stringify({ type: "action", action }));
  }

  return (
    <section className="lc-live" aria-labelledby="live-heading">
      <div className="lc-pagehead">
        <div>
          <p className="tam-eyebrow">Attached mode</p>
          <h1 className="lc-display" id="live-heading">Live project activity</h1>
        </div>
        <span className="lc-chip" data-role={connection === "live" ? "success" : "warning"} role="status">
          {connection}
        </span>
      </div>

      <p className="lc-mobile-live-note lc-panel">
        Live steering is available on larger screens. Today and request resolution remain fully
        available on mobile.
      </p>

      <div className="lc-live-workspace">
        <div className="lc-panel lc-stack lc-stack--4">
          <div className="lc-metaline">
            <span className="tam-eyebrow">Bounded activity</span>
            <span className="lc-meta">Last {events.length} events</span>
          </div>
          <ol className="lc-activity" aria-live="off">
            {events.map((item) => (
              <li className="lc-activity__item" key={item.sequence}>
                <span className="lc-meta">#{item.sequence} · {item.type} · {item.actor}</span>
                <span className="lc-prose">
                  {String(item.detail.summary ?? item.detail.status ?? "Project state changed.")}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <aside className="lc-panel lc-stack lc-stack--4" aria-label="Live steering">
          {canSteer ? (
            <>
              <form className="lc-stack lc-stack--3" onSubmit={submitGuidance}>
                <label className="tam-eyebrow" htmlFor="live-kind">Guidance type</label>
                <select className="lc-select" id="live-kind" name="kind" defaultValue="STEER">
                  <option value="STEER">Steer</option>
                  <option value="ANSWER">Answer</option>
                  <option value="BLOCKER">Report blocker</option>
                </select>
                <label className="tam-eyebrow" htmlFor="live-body">Direction</label>
                <textarea className="lc-writing-input" id="live-body" name="body" rows={7} required />
                <button className="tam-button tam-button--primary" type="submit" disabled={connection !== "live"}>
                  <Send size={16} aria-hidden /> Send guidance
                </button>
              </form>
              <div className="lc-actions" aria-label="Lifecycle actions">
                {allowedActions.map((action) => (
                  <button
                    className="tam-button tam-button--outline"
                    key={action}
                    type="button"
                    onClick={() => sendAction(action)}
                    disabled={connection !== "live"}
                  >
                    {action === "pause" ? <Pause size={16} aria-hidden /> : null}
                    {action === "resume" || action === "start" ? <PlayFilledAlt size={16} aria-hidden /> : null}
                    {action === "stop" ? <Stop size={16} aria-hidden /> : null}
                    {action}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="lc-stack lc-stack--2">
              <p className="tam-eyebrow">Read-only</p>
              <p className="lc-prose lc-prose--muted">
                Your project role can observe this stream but cannot steer or change lifecycle.
              </p>
            </div>
          )}
          {error ? <p className="lc-error" role="alert">{error}</p> : null}
          {connection === "closed" ? (
            <button className="tam-button tam-button--outline" type="button" onClick={() => void connect()}>
              Reconnect
            </button>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
