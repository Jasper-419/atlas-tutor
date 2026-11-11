import type { Metadata } from "next";
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/instrument-serif/400.css";
import "@xyflow/react/dist/style.css";
import "katex/dist/katex.min.css";
import "./globals.css";
import "./learning-desktop.css";
import "./progress-desktop.css";
export const metadata: Metadata = {
  title: "Atlas · 让学习连成路径",
  description:
    "从学习目标到知识掌握，属于你的 AI 学习工作台。课程路径、资料、AI 导师、练习与复习，在这里连接。",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
