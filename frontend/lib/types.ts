export type User = {
  id: number;
  email: string;
  full_name: string;
  is_admin: boolean;
  preferences?: Record<string, unknown>;
};
export type KnowledgeNode = {
  id: string;
  course_id: string;
  title: string;
  summary: string;
  objective: string;
  content: string | null;
  lesson_citations?: Citation[];
  estimated_minutes: number;
  difficulty: string;
  position: number;
  status: "locked" | "available" | "learning" | "mastered";
  mastery: number;
};
export type Course = {
  id: string;
  title: string;
  goal: string;
  background: string;
  minutes_per_day: number;
  deadline: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  progress: number;
  total_nodes: number;
  mastered_nodes: number;
  next_node_id: string | null;
  task_id: string | null;
  plan_version: number;
};
export type Source = {
  id: string;
  course_id: string;
  title: string;
  url: string | null;
  kind: string;
  chunk_count: number;
  created_at: string;
};
export type Citation = {
  id: string;
  source_id: string;
  title: string;
  url: string | null;
  excerpt: string;
  chunk_index: number;
};
export type CourseDetail = Course & {
  nodes: KnowledgeNode[];
  edges: { source: string; target: string }[];
  sources: Source[];
  plan_versions: { version: number; reason: string; created_at: string }[];
};
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
};
export type Exercise = {
  id: string;
  node_id: string;
  type: "choice" | "open";
  prompt: string;
  options: string[];
  rubric: string;
};
export type Attempt = {
  id: string;
  exercise_id: string;
  node_id: string;
  answer: string;
  score: number;
  feedback: string;
  correct_answer: string;
  mastery: number;
  passed: boolean;
  next_node_id: string | null;
  created_at: string;
  prompt?: string;
  node_title?: string;
  course_title?: string;
  course_id?: string;
};
export type Review = {
  id: string;
  node_id: string;
  course_id: string;
  node_title: string;
  course_title: string;
  due_at: string;
  interval_days: number;
  mastery: number;
};
export type Memory = {
  id: string;
  course_id: string | null;
  category: string;
  content: string;
  created_at: string;
  updated_at: string;
  revision?: number;
  status?: string;
  origin?: string;
  facet?: string | null;
  evidence_count?: number;
  source_status?: string;
};
export type Trace = {
  id: string;
  step: string;
  status: string;
  detail: string;
  duration_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  model: string | null;
  created_at: string;
};
export type AgentTask = {
  id: string;
  course_id: string | null;
  kind: "plan" | "research" | "replan" | "ingest";
  status: string;
  progress: number;
  message: string;
  error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  traces: Trace[];
};
export type Template = {
  id: string;
  title: string;
  description: string;
  level: string;
  minutes: number;
  topics: string[];
};
export type Stats = {
  courses: number;
  total_nodes: number;
  mastered_nodes: number;
  due_reviews: number;
  learning_minutes: number;
  attempts?: number;
  average_score?: number;
};
export type DashboardData = {
  courses: Course[];
  stats: Stats;
  activity: { id: string; title: string; detail: string; created_at: string }[];
  reviews: Review[];
  daily_activity: { date: string; attempts: number }[];
};
export type AnalyticsNode = {
  node_id: string;
  course_id: string;
  title: string;
  course_title: string;
  mastery: number;
  status: KnowledgeNode["status"];
};
export type AnalyticsData = {
  stats: Stats;
  daily_activity: { date: string; attempts: number; average_score: number }[];
  mastery: AnalyticsNode[];
  usage: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    average_duration_ms: number;
  };
  weak_nodes: AnalyticsNode[];
};
export type SystemStatus = {
  model_configured: boolean;
  model: string;
  embedding_configured: boolean;
  search_configured: boolean;
  database: string;
  worker: string;
  version: string;
};

export type LLMProtocol =
  | "openai-completions"
  | "openai-responses"
  | "anthropic-messages";
export type LLMConnection = {
  id: string;
  name: string;
  base_url: string;
  protocol: LLMProtocol;
  models: string[];
  model: string;
  has_api_key: boolean;
  updated_at: string;
};
export type LLMConnections = {
  connections: LLMConnection[];
  active_connection_id: string | null;
  server_configured: boolean;
  server_model: string;
};
