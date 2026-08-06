"use client";

import { useFormStatus } from "react-dom";

type PendingButtonProps = {
  children: React.ReactNode;
  pendingLabel?: string;
  kind?: "primary" | "secondary" | "critical";
  name?: string;
  value?: string;
};

export function PendingButton({
  children,
  pendingLabel = "Working…",
  kind = "primary",
  name,
  value,
}: PendingButtonProps) {
  const { pending } = useFormStatus();
  const classes =
    kind === "critical"
      ? "tam-button tam-button--critical"
      : kind === "secondary"
        ? "tam-button tam-button--outline"
        : "tam-button tam-button--primary";
  return (
    <button className={classes} type="submit" disabled={pending} name={name} value={value}>
      {pending ? pendingLabel : children}
    </button>
  );
}
