"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { Root } from "hast";
import type { Plugin } from "unified";
import { remarkPresentation } from "@/lib/markdown-format";
import "./markdown.css";

function CopyButton({ label, readText }: { label: string; readText: () => string }) {
  const [status, setStatus] = useState<"ready" | "copied" | "failed">("ready");
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timeout.current), []);

  async function copy() {
    clearTimeout(timeout.current);
    try {
      await navigator.clipboard.writeText(readText());
      setStatus("copied");
    } catch {
      setStatus("failed");
    }
    timeout.current = setTimeout(() => setStatus("ready"), 1800);
  }

  return <button type="button" className="atlas-output-copy" aria-label={label} onClick={() => void copy()}>
    {status === "copied" ? <Check size={14} /> : <Copy size={14} />}
    <span aria-live="polite">{status === "copied" ? "已复制" : status === "failed" ? "复制失败" : "复制"}</span>
  </button>;
}

export function CodeBlock({ language, children, source, cited }: { language?: string; children: ReactNode; source?: string; cited?: boolean }) {
  const body = useRef<HTMLPreElement>(null);
  return <div className="atlas-output-block atlas-code-block" data-source-citation={cited || undefined}>
    <div className="atlas-output-header">
      <span>{language || "代码"}</span>
      <CopyButton label="复制代码" readText={() => source ?? (body.current?.textContent || "").replace(/\n$/, "")} />
    </div>
    <pre ref={body} tabIndex={0} aria-label={language ? language + " 代码块" : "代码块"}>{children}</pre>
  </div>;
}

function FormulaBlock({ children }: { children: ReactNode }) {
  const body = useRef<HTMLSpanElement>(null);
  return <span className="atlas-output-block atlas-formula-block">
    <span className="atlas-output-header">
      <span>公式</span>
      <CopyButton label="复制公式 LaTeX" readText={() =>
        body.current?.querySelector('annotation[encoding="application/x-tex"]')?.textContent || ""
      } />
    </span>
    <span className="atlas-formula-body" ref={body} tabIndex={0} aria-label="公式块">
      <span className="katex-display">{children}</span>
    </span>
  </span>;
}

const components: Components = {
  a: ({ node: _node, children, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
  pre: ({ node, children }) => {
    const code = node?.children.find((child) => child.type === "element" && child.tagName === "code");
    const classes = code?.type === "element" ? code.properties.className : undefined;
    const language = Array.isArray(classes)
      ? classes.find((value): value is string => typeof value === "string" && value.startsWith("language-"))?.slice(9, 41)
      : undefined;
    return <CodeBlock language={language} cited={node?.properties.dataSourceCitation === true}>{children}</CodeBlock>;
  },
  span: ({ node: _node, className, children, ...props }) =>
    className?.split(" ").includes("katex-display")
      ? <FormulaBlock>{children}</FormulaBlock>
      : <span {...props} className={className}>{children}</span>,
};

type CitationRange = [start: number, end: number];

const rehypeCitedBlocks: Plugin<[CitationRange | null | undefined], Root> = (range) => (tree) => {
  if (!range) return;
  for (const node of tree.children) {
    if (node.type !== "element" || node.tagName === "hr") continue;
    const start = node.position?.start.offset;
    const end = node.position?.end.offset;
    if (start !== undefined && end !== undefined && start < range[1] && end > range[0]) {
      node.properties.dataSourceCitation = true;
    }
  }
};

export function Markdown({ children, citationRange }: { children: string; citationRange?: CitationRange | null }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={citationRange === undefined ? [remarkGfm, remarkMath, remarkPresentation] : [remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeCitedBlocks, citationRange], [rehypeKatex, { trust: false, maxSize: 20 }], [rehypeHighlight, { detect: false }]]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
