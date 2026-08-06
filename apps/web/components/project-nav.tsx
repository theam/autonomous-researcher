import Link from "next/link";

type ProjectSection = "overview" | "knowledge" | "runs" | "live" | "settings";

type Props = { slug: string; active: ProjectSection };

const sections: Array<{ id: ProjectSection; label: string; suffix: string }> = [
  { id: "overview", label: "Overview", suffix: "" },
  { id: "knowledge", label: "Knowledge", suffix: "/knowledge" },
  { id: "runs", label: "Runs", suffix: "/runs" },
  { id: "live", label: "Live", suffix: "/live" },
  { id: "settings", label: "Settings", suffix: "/settings" },
];

export function ProjectNav({ slug, active }: Props) {
  const base = `/projects/${encodeURIComponent(slug)}`;
  return (
    <nav className="lc-project-tabs" aria-label="Project sections">
      {sections.map((section) => (
        <Link
          aria-current={active === section.id ? "page" : undefined}
          href={`${base}${section.suffix}`}
          key={section.id}
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
