"use client";

import { useState, useRef } from "react";
import type {
  ArticleTone,
  OrchestrationResult,
  OrchestrationStepStatus,
  EditChange,
} from "@/agents/types";

// ── Constants ────────────────────────────────────────────────────────────

const TONES: { value: ArticleTone; label: string; desc: string }[] = [
  { value: "professional", label: "Professional", desc: "Business-ready" },
  { value: "casual", label: "Casual", desc: "Relaxed & friendly" },
  { value: "academic", label: "Academic", desc: "Scholarly & precise" },
  { value: "journalistic", label: "Journalistic", desc: "News-style" },
];

interface AgentMeta {
  label: string;
  icon: string;
  accent: string;
  accentBg: string;
  accentBorder: string;
  desc: string;
}

const AGENTS: Record<string, AgentMeta> = {
  research: {
    label: "Research Agent",
    icon: "M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z",
    accent: "text-blue-400",
    accentBg: "bg-blue-500/10",
    accentBorder: "border-blue-500/20",
    desc: "Searching the web & extracting facts",
  },
  writer: {
    label: "Writer Agent",
    icon: "M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10",
    accent: "text-emerald-400",
    accentBg: "bg-emerald-500/10",
    accentBorder: "border-emerald-500/20",
    desc: "Composing a structured article",
  },
  editor: {
    label: "Editor Agent",
    icon: "M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42",
    accent: "text-purple-400",
    accentBg: "bg-purple-500/10",
    accentBorder: "border-purple-500/20",
    desc: "Polishing grammar, clarity & headlines",
  },
};

const CHANGE_COLORS: Record<EditChange["type"], string> = {
  grammar: "bg-amber-500/15 text-amber-300 border-amber-500/20",
  clarity: "bg-sky-500/15 text-sky-300 border-sky-500/20",
  redundancy: "bg-orange-500/15 text-orange-300 border-orange-500/20",
  headline: "bg-violet-500/15 text-violet-300 border-violet-500/20",
  structure: "bg-teal-500/15 text-teal-300 border-teal-500/20",
};

// ── Main component ───────────────────────────────────────────────────────

export default function Home() {
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState<ArticleTone>("professional");
  const [result, setResult] = useState<OrchestrationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  async function runPipeline() {
    if (!topic.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setActiveAgent("research");

    // Simulate step progression for the loading UI
    const agentTimer = setTimeout(() => setActiveAgent("writer"), 1500);
    const agentTimer2 = setTimeout(() => setActiveAgent("editor"), 2500);

    try {
      const res = await fetch("/api/orchestrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic.trim(), tone }),
      });

      const data = await res.json();

      if (!res.ok && !data.steps) {
        throw new Error(data.error ?? "Pipeline request failed");
      }

      setResult(data as OrchestrationResult);

      // Scroll to results
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      clearTimeout(agentTimer);
      clearTimeout(agentTimer2);
      setLoading(false);
      setActiveAgent(null);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950">
      {/* ── Hero / Input Section ────────────────────────────────────── */}
      <div className="relative overflow-hidden">
        {/* Gradient background */}
        <div className="absolute inset-0 bg-gradient-to-b from-blue-950/30 via-zinc-950 to-zinc-950" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-blue-500/5 rounded-full blur-3xl" />

        <div className="relative mx-auto max-w-3xl px-6 pt-20 pb-16">
          {/* Logo / Title */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/80 px-4 py-1.5 text-xs text-zinc-400 mb-6 backdrop-blur-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Multi-Agent Pipeline
            </div>
            <h1 className="text-5xl font-bold tracking-tight text-white mb-3">
              Content Studio
            </h1>
            <p className="text-lg text-zinc-400 max-w-md mx-auto">
              Enter a topic and watch three AI agents research, write, and edit a polished article.
            </p>
          </div>

          {/* Input card */}
          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/60 p-6 backdrop-blur-sm shadow-2xl shadow-black/20">
            {/* Topic input */}
            <div className="relative mb-4">
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !loading && runPipeline()}
                placeholder="What should we write about?"
                className="w-full rounded-xl border border-zinc-700/60 bg-zinc-800/50 px-5 py-4 text-lg text-white placeholder-zinc-500 outline-none transition-all focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/10"
              />
            </div>

            {/* Tone selector */}
            <div className="grid grid-cols-4 gap-2 mb-5">
              {TONES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setTone(t.value)}
                  className={`rounded-lg border px-3 py-2.5 text-left transition-all ${
                    tone === t.value
                      ? "border-blue-500/40 bg-blue-500/10 text-white"
                      : "border-zinc-700/40 bg-zinc-800/30 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300"
                  }`}
                >
                  <div className="text-sm font-medium">{t.label}</div>
                  <div className="text-xs opacity-60">{t.desc}</div>
                </button>
              ))}
            </div>

            {/* Generate button */}
            <button
              onClick={runPipeline}
              disabled={loading || !topic.trim()}
              className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 py-4 text-base font-semibold text-white shadow-lg shadow-blue-500/20 transition-all hover:from-blue-500 hover:to-blue-400 hover:shadow-blue-500/30 disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none active:scale-[0.99]"
            >
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  <Spinner />
                  Generating Content...
                </span>
              ) : (
                "Generate Content"
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ── Agent Progress Stepper (loading) ───────────────────────── */}
      {loading && (
        <div className="mx-auto max-w-3xl px-6 pb-8 animate-fade-in">
          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/60 p-6 backdrop-blur-sm">
            <div className="flex items-center justify-between mb-6">
              {(["research", "writer", "editor"] as const).map((agentId, i) => {
                const meta = AGENTS[agentId];
                const isActive = activeAgent === agentId;
                const isPast =
                  activeAgent === "writer" && agentId === "research" ||
                  activeAgent === "editor" && (agentId === "research" || agentId === "writer");

                return (
                  <div key={agentId} className="flex items-center flex-1">
                    <div className="flex flex-col items-center flex-1">
                      <div
                        className={`relative flex h-12 w-12 items-center justify-center rounded-full border-2 transition-all duration-500 ${
                          isActive
                            ? `${meta.accentBorder} ${meta.accentBg}`
                            : isPast
                            ? "border-emerald-500/40 bg-emerald-500/10"
                            : "border-zinc-700 bg-zinc-800/50"
                        }`}
                      >
                        {isActive && (
                          <div className={`absolute inset-0 rounded-full ${meta.accentBg} animate-pulse-ring`} />
                        )}
                        {isPast ? (
                          <svg className="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                          </svg>
                        ) : (
                          <svg
                            className={`h-5 w-5 transition-colors ${isActive ? meta.accent : "text-zinc-500"}`}
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={1.5}
                            stroke="currentColor"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d={meta.icon} />
                          </svg>
                        )}
                      </div>
                      <span className={`mt-2 text-xs font-medium transition-colors ${isActive ? meta.accent : isPast ? "text-emerald-400" : "text-zinc-500"}`}>
                        {meta.label}
                      </span>
                      {isActive && (
                        <span className="mt-1 text-[11px] text-zinc-500 animate-fade-in">{meta.desc}</span>
                      )}
                    </div>
                    {i < 2 && (
                      <div className={`h-px flex-1 mx-2 mt-[-20px] transition-colors duration-500 ${isPast ? "bg-emerald-500/30" : "bg-zinc-800"}`} />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Shimmer loading bars */}
            <div className="space-y-2">
              <div className="h-3 rounded-full bg-zinc-800 animate-shimmer" />
              <div className="h-3 w-3/4 rounded-full bg-zinc-800 animate-shimmer" style={{ animationDelay: "200ms" }} />
              <div className="h-3 w-1/2 rounded-full bg-zinc-800 animate-shimmer" style={{ animationDelay: "400ms" }} />
            </div>
          </div>
        </div>
      )}

      {/* ── Error ──────────────────────────────────────────────────── */}
      {error && (
        <div className="mx-auto max-w-3xl px-6 pb-8 animate-fade-in">
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 flex items-start gap-3">
            <svg className="h-5 w-5 text-red-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-red-300">Pipeline Error</p>
              <p className="text-sm text-red-400/80 mt-0.5">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Results ────────────────────────────────────────────────── */}
      {result && (
        <div ref={resultsRef} className="mx-auto max-w-5xl px-6 pb-20">
          {/* Pipeline status bar */}
          <div className="mb-8 animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
              <PipelineStatusIcon status={result.status} />
              <h2 className="text-2xl font-bold text-white">Results</h2>
              <span className="ml-auto text-sm text-zinc-500">
                {(result.totalDurationMs / 1000).toFixed(1)}s
              </span>
            </div>

            {/* Step pills */}
            <div className="flex gap-2">
              {result.steps.map((step) => {
                const meta = AGENTS[step.agent];
                return (
                  <StepPill
                    key={step.agent}
                    label={meta?.label ?? step.agent}
                    status={step.status}
                    durationMs={step.durationMs}
                    accent={meta?.accent ?? "text-zinc-400"}
                    error={step.error}
                  />
                );
              })}
            </div>
          </div>

          {/* Three agent work sections */}
          <div className="space-y-6 stagger-children">
            {/* ── 1. Research ──────────────────────────────────────── */}
            {result.research && (
              <AgentCard agent="research">
                <p className="text-sm text-zinc-400 mb-4">{result.research.summary}</p>

                <div className="space-y-3 mb-4">
                  {result.research.facts.map((f, i) => (
                    <div
                      key={i}
                      className="flex gap-3 rounded-lg border border-zinc-800/60 bg-zinc-800/20 p-3"
                    >
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/10 text-xs font-bold text-blue-400">
                        {i + 1}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm text-zinc-300 leading-relaxed">{f.fact}</p>
                        <a
                          href={f.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-block text-xs text-blue-500 hover:text-blue-400 truncate max-w-full"
                        >
                          {f.sourceTitle}
                        </a>
                      </div>
                    </div>
                  ))}
                </div>

                <details className="group">
                  <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
                    View {result.research.sources.length} sources & search queries
                  </summary>
                  <div className="mt-3 rounded-lg border border-zinc-800/60 bg-zinc-800/20 p-3 space-y-1.5">
                    {result.research.sources.map((s, i) => (
                      <a
                        key={i}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-xs text-blue-500/80 hover:text-blue-400 truncate"
                      >
                        {s.title}
                      </a>
                    ))}
                    <p className="text-xs text-zinc-600 mt-2 pt-2 border-t border-zinc-800">
                      Queries: {result.research.searchQueries.join("  /  ")}
                    </p>
                  </div>
                </details>
              </AgentCard>
            )}

            {/* ── 2. Writer ────────────────────────────────────────── */}
            {result.article && (
              <AgentCard agent="writer">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <h3 className="text-lg font-semibold text-white leading-snug">
                    {result.article.title}
                  </h3>
                  <div className="flex gap-2 shrink-0">
                    <Pill>{result.article.wordCount} words</Pill>
                    <Pill>{result.article.citations.length} sources</Pill>
                  </div>
                </div>
                <div className="whitespace-pre-wrap text-sm text-zinc-400 leading-relaxed rounded-lg border border-zinc-800/60 bg-zinc-800/20 p-4 max-h-64 overflow-y-auto">
                  {result.article.article}
                </div>
              </AgentCard>
            )}

            {/* ── 3. Editor ────────────────────────────────────────── */}
            {result.edited && (
              <AgentCard agent="editor">
                {/* Quality scores */}
                <div className="grid grid-cols-5 gap-3 mb-5">
                  {(Object.entries(result.edited.qualityScore) as [string, number][]).map(
                    ([key, val]) => (
                      <ScoreCard key={key} label={key} value={val} />
                    )
                  )}
                </div>

                {/* Changes summary */}
                {result.edited.changes.length > 0 && (
                  <div className="mb-4">
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {groupChanges(result.edited.changes).map(([type, count]) => (
                        <span
                          key={type}
                          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${CHANGE_COLORS[type as EditChange["type"]]}`}
                        >
                          {type}
                          <span className="opacity-60">{count}</span>
                        </span>
                      ))}
                    </div>

                    <details className="group">
                      <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
                        View all {result.edited.changes.length} changes
                      </summary>
                      <ul className="mt-3 space-y-2">
                        {result.edited.changes.map((c, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                            <span className={`shrink-0 mt-0.5 rounded border px-1.5 py-0.5 font-medium ${CHANGE_COLORS[c.type]}`}>
                              {c.type}
                            </span>
                            <span>
                              {c.reason}
                              {c.type !== "headline" && c.type !== "structure" && (
                                <span className="text-zinc-600 ml-1">
                                  <s>{c.original}</s>{" "}
                                  <span className="text-zinc-400">&rarr;</span>{" "}
                                  <span className="text-emerald-400/70">{c.replacement}</span>
                                </span>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>
                )}

                {/* Headline suggestions */}
                <div className="flex flex-wrap gap-2 mb-4">
                  {result.edited.headlineSuggestions.map((h, i) => (
                    <span
                      key={i}
                      className={`text-xs rounded-lg border px-3 py-1.5 ${
                        i === 0
                          ? "border-purple-500/30 bg-purple-500/10 text-purple-300"
                          : "border-zinc-700/50 bg-zinc-800/30 text-zinc-400"
                      }`}
                    >
                      {h}
                    </span>
                  ))}
                </div>
              </AgentCard>
            )}
          </div>

          {/* ── Final Output (prominent) ───────────────────────────── */}
          {result.edited && (
            <div className="mt-10 animate-fade-in-up" style={{ animationDelay: "500ms" }}>
              <div className="rounded-2xl border border-zinc-700/50 bg-gradient-to-b from-zinc-900 to-zinc-900/50 p-8 shadow-2xl shadow-black/30">
                <div className="flex items-center gap-3 mb-6">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-purple-500">
                    <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>
                  <h2 className="text-2xl font-bold text-white">Final Article</h2>
                  <div className="ml-auto flex gap-2">
                    <Pill>{result.edited.wordCount} words</Pill>
                    <Pill>Score: {result.edited.qualityScore.overall}/100</Pill>
                  </div>
                </div>

                <h3 className="text-xl font-bold text-white mb-4 leading-snug">
                  {result.edited.editedTitle}
                </h3>

                <article className="whitespace-pre-wrap text-[15px] text-zinc-300 leading-[1.8] mb-6">
                  {result.edited.editedArticle}
                </article>

                {/* Citation footer */}
                {result.edited.citations.length > 0 && (
                  <div className="border-t border-zinc-800 pt-4">
                    <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                      Sources
                    </h4>
                    <div className="space-y-1">
                      {result.edited.citations.map((c) => (
                        <div key={c.index} className="flex items-baseline gap-2 text-xs">
                          <span className="text-zinc-600 font-mono">[{c.index}]</span>
                          <a
                            href={c.sourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-500/70 hover:text-blue-400 truncate"
                          >
                            {c.sourceTitle}
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────

function Spinner() {
  return (
    <svg className="h-5 w-5 animate-spin-slow" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md border border-zinc-700/50 bg-zinc-800/50 px-2 py-0.5 text-xs text-zinc-400">
      {children}
    </span>
  );
}

function PipelineStatusIcon({ status }: { status: OrchestrationResult["status"] }) {
  if (status === "completed") {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/15">
        <svg className="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </div>
    );
  }
  if (status === "partial") {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-yellow-500/15">
        <svg className="h-4 w-4 text-yellow-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
      </div>
    );
  }
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/15">
      <svg className="h-4 w-4 text-red-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </div>
  );
}

function StepPill({
  label,
  status,
  durationMs,
  accent,
  error,
}: {
  label: string;
  status: OrchestrationStepStatus;
  durationMs: number;
  accent: string;
  error?: string;
}) {
  const statusStyles: Record<string, string> = {
    completed: "border-emerald-500/20 bg-emerald-500/5",
    failed: "border-red-500/20 bg-red-500/5",
    skipped: "border-zinc-700/30 bg-zinc-800/20 opacity-50",
    pending: "border-zinc-700/30 bg-zinc-800/20",
    running: "border-blue-500/20 bg-blue-500/5",
  };

  const dotColor: Record<string, string> = {
    completed: "bg-emerald-400",
    failed: "bg-red-400",
    skipped: "bg-zinc-600",
    pending: "bg-zinc-600",
    running: "bg-blue-400 animate-pulse",
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${statusStyles[status]}`}
      title={error}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotColor[status]}`} />
      <span className={accent}>{label}</span>
      {durationMs > 0 && (
        <span className="text-zinc-600">{durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s`}</span>
      )}
      {status === "failed" && (
        <svg className="h-3 w-3 text-red-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
      )}
    </div>
  );
}

function AgentCard({ agent, children }: { agent: string; children: React.ReactNode }) {
  const meta = AGENTS[agent];
  if (!meta) return null;

  return (
    <div className={`rounded-xl border ${meta.accentBorder} bg-zinc-900/80 overflow-hidden`}>
      {/* Header */}
      <div className={`flex items-center gap-3 px-5 py-3 border-b ${meta.accentBorder} ${meta.accentBg}`}>
        <svg className={`h-4 w-4 ${meta.accent}`} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d={meta.icon} />
        </svg>
        <span className={`text-sm font-semibold ${meta.accent}`}>{meta.label}</span>
      </div>
      {/* Body */}
      <div className="p-5">{children}</div>
    </div>
  );
}

function ScoreCard({ label, value }: { label: string; value: number }) {
  const color =
    value >= 85 ? "text-emerald-400" : value >= 70 ? "text-yellow-400" : "text-red-400";
  const barColor =
    value >= 85
      ? "bg-gradient-to-r from-emerald-600 to-emerald-400"
      : value >= 70
      ? "bg-gradient-to-r from-yellow-600 to-yellow-400"
      : "bg-gradient-to-r from-red-600 to-red-400";

  return (
    <div className="rounded-lg border border-zinc-800/60 bg-zinc-800/20 p-3">
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-xs text-zinc-500 capitalize">{label}</span>
        <span className={`text-sm font-bold ${color}`}>{value}</span>
      </div>
      <div className="h-1.5 rounded-full bg-zinc-800">
        <div
          className={`h-1.5 rounded-full ${barColor} animate-progress-fill`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

// ── Utilities ────────────────────────────────────────────────────────────

function groupChanges(changes: EditChange[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const c of changes) {
    counts.set(c.type, (counts.get(c.type) ?? 0) + 1);
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}
