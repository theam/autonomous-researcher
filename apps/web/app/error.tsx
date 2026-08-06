"use client";

import Link from "next/link";
import { useEffect } from "react";

import { LiminaMark } from "@/components/limina-mark";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="lc-main" id="main">
      <div className="lc-bounds lc-stack lc-stack--5">
        <LiminaMark size={32} title="Limina Console" />
        <p className="tam-eyebrow">Console error</p>
        <h1 className="lc-display">This view could not be loaded.</h1>
        <p className="lc-prose lc-prose--lead">
          The runtime may be temporarily unavailable. No operator action was applied.
        </p>
        <div className="lc-action-row">
          <button className="tam-button tam-button--primary" type="button" onClick={reset}>
            Try again
          </button>
          <Link className="tam-button tam-button--outline" href="/">
            Return to Today
          </Link>
        </div>
      </div>
    </main>
  );
}
