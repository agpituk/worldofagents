"use client";

// Hosted deploy page — paste a YAML manifest, register a hero, get a share
// URL and the runtime command. The actual bot-runner still runs locally
// (the `python -m arena_bot ...` command) — a managed runtime is on the
// roadmap but not in scope today. This page is the onboarding wall removal:
// no clone, no make dev, just paste-and-go.

import Link from "next/link";
import dynamic from "next/dynamic";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { rememberOwnedHero } from "@/lib/heroOwnership";
import DeployIntro from "./components/DeployIntro";
import ValidationPanel from "./components/ValidationPanel";
import SimulationPanel from "./components/SimulationPanel";
import ToolsPreview from "./components/ToolsPreview";
import ManagedToggle from "./components/ManagedToggle";
import DeployActions from "./components/DeployActions";
import PostDeploySuccess, { type RegisteredHero } from "./components/PostDeploySuccess";
import { STARTER_MANIFEST, manifestYamlFromHero } from "./components/manifestTemplates";
import BuildPanel, { parseBuild } from "./components/BuildPanel";
import TemplateModal from "./components/TemplateModal";
import type { Archetype } from "./templates/templates";

const ONBOARDED_KEY = "worldofagents:onboarded";

// Blockly is heavy (~280KB gzipped) — lazy-load only on /deploy.
const BlockEditor = dynamic(() => import("@/components/BlockEditor"), {
  ssr: false,
  loading: () => (
    <div className="border border-border bg-bg-card p-6 text-xs text-fg-muted">
      loading block editor...
    </div>
  ),
});

function DeployFormBody() {
  const params = useSearchParams();
  const forkId = params.get("fork");
  const [manifest, setManifest] = useState(STARTER_MANIFEST);
  const [forkSource, setForkSource] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [managed, setManaged] = useState(true); // default ON — paste-and-go
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // First-visit gate. Only show the picker when the user has neither forked
  // nor onboarded before. The flag is set as soon as a card is clicked OR
  // the modal is dismissed, so we don't nag.
  useEffect(() => {
    if (forkId) return;
    try {
      const seen = window.localStorage.getItem(ONBOARDED_KEY);
      if (!seen) setShowTemplateModal(true);
    } catch {
      // localStorage may be unavailable (private mode); fail open — no modal.
    }
  }, [forkId]);

  function pickTemplate(a: Archetype) {
    setManifest(a.yaml);
    setTemplateName(a.name);
    setShowTemplateModal(false);
    try {
      window.localStorage.setItem(ONBOARDED_KEY, "1");
    } catch {}
  }

  function dismissTemplateModal() {
    setShowTemplateModal(false);
    try {
      window.localStorage.setItem(ONBOARDED_KEY, "1");
    } catch {}
  }

  // Phase 8 — load the source hero's public manifest and prefill the
  // textarea when /deploy?fork=<id> is opened. Failure is silent so a
  // stale URL doesn't lock anyone out — they can still type freely.
  useEffect(() => {
    if (!forkId) return;
    let live = true;
    api.getHero(forkId).then((h: any) => {
      if (!live) return;
      setForkSource(h.name);
      setManifest(manifestYamlFromHero(h));
    }).catch(() => {});
    return () => { live = false; };
  }, [forkId]);
  const [registered, setRegistered] = useState<RegisteredHero | null>(null);

  // Phase 8 — manifest validator. Stays empty until the user clicks
  // "validate"; results are issue-level (severity + path + message)
  // and clear when they edit the manifest so stale lints don't linger.
  const [validation, setValidation] = useState<{ valid: boolean; issues: any[]; summary: any } | null>(null);
  const [validating, setValidating] = useState(false);

  async function validate() {
    setValidating(true);
    setValidation(null);
    try {
      const res = await api.validateManifest(manifest);
      setValidation(res);
    } catch (e: any) {
      setValidation({ valid: false, issues: [{ severity: "error", message: String(e?.message ?? "validate failed") }], summary: {} });
    } finally {
      setValidating(false);
    }
  }

  async function deploy() {
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.registerHero(manifest, { managed });
      rememberOwnedHero(r.id, r.auth_token);
      setRegistered({ ...r, managed });
    } catch (e: any) {
      setError(String(e?.message ?? "registration failed"));
    } finally {
      setSubmitting(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const text = await f.text();
    setManifest(text);
  }

  if (registered) {
    return (
      <PostDeploySuccess
        registered={registered}
        onDeployAnother={() => {
          setRegistered(null);
          setManifest(STARTER_MANIFEST);
          setTemplateName(null);
        }}
      />
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <TemplateModal
        open={showTemplateModal}
        onPick={pickTemplate}
        onSkip={dismissTemplateModal}
      />

      <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>

      <DeployIntro
        forkSource={forkSource}
        onUpload={onFile}
        onReset={() => {
          setManifest(STARTER_MANIFEST);
          setTemplateName(null);
        }}
      />

      {templateName && (
        <div className="text-xs text-fg-muted flex items-center gap-2">
          <span className="border border-amber-dim/40 text-amber-dim px-2 py-0.5">
            Template: {templateName}
          </span>
          <span>— edit freely. Replace the <code>@template</code> author with your handle.</span>
        </div>
      )}

      <BuildPanel
        value={manifest}
        onChange={(next) => {
          setManifest(next);
          setValidation(null);
        }}
      />

      <BlockEditor
        value={manifest}
        onChange={(next) => {
          setManifest(next);
          setValidation(null);
        }}
        validationIssues={validation?.issues}
      />

      <ValidationPanel
        manifest={manifest}
        validation={validation}
        validating={validating}
        onValidate={validate}
      />

      {/* First-tick simulation panel — runs reflex eval + tool spec
          assembly server-side against a synthetic perception. */}
      <SimulationPanel manifest={manifest} />

      {validation?.valid && Array.isArray(validation.summary?.tools) && (
        <ToolsPreview tools={validation.summary.tools} />
      )}

      <ManagedToggle managed={managed} onChange={setManaged} />

      <DeployActions
        manifest={manifest}
        submitting={submitting}
        error={error}
        onDeploy={deploy}
        disabledReason={(() => {
          const b = parseBuild(manifest);
          if (!b) return null;
          const total = b.str + b.dex + b.con + b.int + b.wis + b.cha;
          if (total > 100) return `over budget by ${total - 100} — server will reject`;
          return null;
        })()}
      />
    </div>
  );
}

export default function DeployPage() {
  return (
    <Suspense fallback={<div className='text-fg-muted'>loading…</div>}>
      <DeployFormBody />
    </Suspense>
  );
}
