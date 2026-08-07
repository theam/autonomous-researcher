import { ConsoleFrame } from "@/components/console-frame";
import { PendingButton } from "@/components/pending-button";
import { createProjectAction } from "@/app/actions";
import { getMe, listTemplates } from "@/lib/limina/server";

export default async function NewProjectPage() {
  const [me, templates] = await Promise.all([getMe(), listTemplates()]);
  return (
    <ConsoleFrame activeNav="new">
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Kickoff · four stages</p>
          <h1 className="lc-display">Frame a research mission</h1>
          <p className="lc-prose lc-prose--muted">Create the durable brief first. You can add inputs and run preflight before starting.</p>
        </div>
      </div>
      <form action={createProjectAction} className="lc-kickoff">
        <section className="lc-panel lc-stack lc-stack--4" aria-labelledby="mission-step">
          <div className="lc-step-title"><span>1</span><h2 id="mission-step">Mission</h2></div>
          <label className="tam-eyebrow" htmlFor="template">Starting pattern</label>
          <select className="lc-select" id="template" defaultValue="">
            <option value="">Choose a reference pattern</option>
            {templates.map((template) => <option value={template.id} key={template.id}>{template.name}</option>)}
          </select>
          <p className="lc-meta">Patterns are guidance only; the submitted brief below remains authoritative.</p>
          <label className="tam-eyebrow" htmlFor="name">Project name</label>
          <input className="lc-writing-input" id="name" name="name" required maxLength={240} />
          <label className="tam-eyebrow" htmlFor="slug">Stable slug</label>
          <input className="lc-writing-input" id="slug" name="slug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" required maxLength={120} />
          <label className="tam-eyebrow" htmlFor="objective">Mission</label>
          <textarea className="lc-writing-input" id="objective" name="objective" rows={5} required />
          <label className="tam-eyebrow" htmlFor="success-criteria">Success criteria</label>
          <textarea className="lc-writing-input" id="success-criteria" name="success_criteria" rows={4} required />
          <label className="tam-eyebrow" htmlFor="context">Context and strongest baseline</label>
          <textarea className="lc-writing-input" id="context" name="context" rows={5} />
        </section>
        <section className="lc-panel lc-stack lc-stack--4" aria-labelledby="runtime-step">
          <div className="lc-step-title"><span>2</span><h2 id="runtime-step">Runtime</h2></div>
          <p className="lc-prose lc-prose--muted">The engine is fixed after work starts so evidence and continuation provenance remain honest.</p>
          <fieldset className="lc-choice-fieldset">
            <legend className="tam-eyebrow">Choose an executor</legend>
            {me.available_runtimes.map((runtime) => (
              <label className="lc-radio-row" key={runtime}>
                <input type="radio" name="runtime" value={runtime} defaultChecked={runtime === "codex"} />
                <span><strong>{runtime === "codex" ? "Codex" : "Claude Code"}</strong><small>{runtime === "codex" ? "OpenAI coding and research runtime" : "Anthropic coding and research runtime"}</small></span>
              </label>
            ))}
          </fieldset>
        </section>
        <section className="lc-panel lc-stack lc-stack--3" aria-labelledby="inputs-step">
          <div className="lc-step-title"><span>3</span><h2 id="inputs-step">Inputs</h2></div>
          <p className="lc-prose">Create the brief now, then add URLs, uploads, variables, and write-only secrets from Project Settings before starting.</p>
        </section>
        <section className="lc-panel lc-stack lc-stack--3" aria-labelledby="review-step">
          <div className="lc-step-title"><span>4</span><h2 id="review-step">Review and preflight</h2></div>
          <p className="lc-prose">Creation does not start execution. The project Overview will show typed preflight checks and the server-authorized Start action.</p>
          <PendingButton pendingLabel="Creating project…">Create draft</PendingButton>
        </section>
      </form>
    </ConsoleFrame>
  );
}
