import Link from "next/link";

import { ConsoleFrame } from "@/components/console-frame";

export default function NotFoundPage() {
  return (
    <ConsoleFrame activeNav="today">
      <section className="lc-panel lc-stack lc-stack--4">
        <p className="tam-eyebrow">Not found</p>
        <h1 className="lc-display">That Console item is no longer available.</h1>
        <p className="lc-prose lc-prose--lead">
          It may have been resolved, archived, or outside your current project access.
        </p>
        <Link className="tam-button tam-button--primary" href="/">
          View the current queue
        </Link>
      </section>
    </ConsoleFrame>
  );
}
