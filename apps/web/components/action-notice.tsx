"use client";

import { useEffect, useRef } from "react";

export type NoticeCode = "resolved" | "changed" | "gone" | "failed";

const notices: Record<NoticeCode, { message: string; critical: boolean }> = {
  resolved: { message: "The executor response was recorded.", critical: false },
  changed: {
    message: "This item changed before your response was saved. Review its current state and try again.",
    critical: true,
  },
  gone: {
    message: "This attention item is no longer available. The queue now shows the current state.",
    critical: false,
  },
  failed: {
    message: "Limina could not record that response. No decision was applied; try again.",
    critical: true,
  },
};

export function ActionNotice({ code }: { code?: NoticeCode }) {
  const noticeRef = useRef<HTMLDivElement>(null);
  const notice = code ? notices[code] : undefined;

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  if (!notice) return null;
  return (
    <div
      className="lc-action-notice"
      data-critical={notice.critical}
      role={notice.critical ? "alert" : "status"}
      tabIndex={-1}
      ref={noticeRef}
    >
      {notice.message}
    </div>
  );
}
