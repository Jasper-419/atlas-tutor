import type { Code, Root } from "mdast";
import type { Plugin } from "unified";
import type { Node, Parent } from "unist";

const literalNodes = new Set(["code", "inlineCode", "math", "inlineMath", "html", "link", "image", "definition"]);
const mathDelimiters = /^(?<indent>[ \t]{0,3})(?:\\\[(?<display>[\s\S]+?)\\\]|\$\$(?<compact>[^\r\n]+?)\$\$)[ \t]*(?=\r?$)|(?<!\\)\\\((?<inline>[^\r\n]+?)(?<!\\)\\\)/gm;

function normalizeMath(source: string, tree: Root) {
  if (!source.includes("\\(") && !source.includes("\\[") && !source.includes("$$")) return source;
  const protectedRanges: [number, number][] = [];
  function protect(node: Node) {
    if (literalNodes.has(node.type)) {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (start === undefined || end === undefined) return;
      // A double-dollar expression on its own line is display math.
      if (node.type === "inlineMath" && source.slice(start, end).startsWith("$$")) {
        const lineStart = source.lastIndexOf("\n", start - 1) + 1;
        const lineEnd = source.indexOf("\n", end);
        const before = source.slice(lineStart, start);
        const after = source.slice(end, lineEnd === -1 ? source.length : lineEnd);
        if (!before.trim() && !after.trim()) return;
      }
      protectedRanges.push([start, end]);
    } else if ("children" in node) {
      (node as Parent).children.forEach(protect);
    }
  }
  protect(tree);

  function normalizeSegment(start: number, end: number) {
    const segment = source.slice(start, end);
    let output = "";
    let previous = 0;
    for (const match of segment.matchAll(mathDelimiters)) {
      const { indent, display, compact, inline } = match.groups!;
      const body = (display ?? compact ?? inline).trim();
      if (!body || (inline === undefined && match.index === 0 && start > 0 && source[start - 1] !== "\n")) continue;
      const replacement = inline === undefined
        ? indent + "$$\n" + body.split(/\r?\n/).map((line) => indent + line).join("\n") + "\n" + indent + "$$"
        : "$" + body + "$";
      output += segment.slice(previous, match.index) + replacement;
      previous = match.index + match[0].length;
    }
    return output + segment.slice(previous);
  }

  let previous = 0;
  let output = "";
  for (const [start, end] of protectedRanges) {
    output += normalizeSegment(previous, start) + source.slice(start, end);
    previous = end;
  }
  return output + normalizeSegment(previous, source.length);
}

function joinAdjacentCode(parent: Parent) {
  let previous: Code | undefined;
  parent.children = parent.children.filter((node) => {
    if (node.type !== "code") {
      previous = undefined;
      if ("children" in node) joinAdjacentCode(node as Parent);
      return true;
    }
    const block = node as Code;
    if (previous && block.lang !== "math" && block.lang === previous.lang && block.meta === previous.meta) {
      previous.value += "\n\n" + block.value;
      return false;
    }
    previous = block;
    return true;
  });
}

export const remarkPresentation: Plugin<[], Root> = function () {
  const processor = this;
  return (tree, file) => {
    const original = String(file);
    const normalized = normalizeMath(original, tree);
    if (normalized !== original) {
      file.value = normalized;
      tree = processor.parse(file) as Root;
    }
    joinAdjacentCode(tree);
    return tree;
  };
};
