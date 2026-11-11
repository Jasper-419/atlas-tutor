"""Turn-owned behavior and completion checks, separate from tool permissions."""

from dataclasses import dataclass
from typing import Literal

CapabilityName = Literal["tutor", "qa", "research", "planner", "solve"]


@dataclass(frozen=True)
class TurnCapability:
    name: str
    title: str
    description: str
    profile: str
    instructions: str

    def prepare(self, checkpoint):
        checkpoint.setdefault("agent", {})["prepared_capability"] = self.name
        return {"role": "system", "content": self.instructions}

    def ready_to_finish(self, checkpoint):
        return self.name != "solve" or checkpoint.get("solve", {}).get("status") == "completed"

    def result(self, checkpoint, status):
        from backend.agent.contracts import CapabilityResult
        failures = any(value.get("status") in {"failed", "uncertain"} for value in checkpoint.get("tool_receipts", {}).values())
        outcome = "cancelled" if status == "cancelled" else "failed" if status == "failed" else "answered_with_errors" if failures else "answered"
        verified = reasoned = 0
        limitations = []
        if self.name == "solve":
            state = checkpoint.get("solve", {})
            steps = state.get("steps", [])
            verified = sum(step.get("status") == "verified" for step in steps)
            reasoned = sum(step.get("status") == "reasoned" for step in steps)
            if status == "completed":
                outcome = "incomplete" if state.get("status") != "completed" else "verified" if steps and verified == len(steps) else "partially_verified" if verified else "unverified"
            limitations = ["Python 校验只证明所列检查的实际结果；检查由 Agent 提出，不构成数学证明或全部输入的正确性保证。", "推理说明步骤未经过可执行验证；执行器仅支持受限 Python 子集。"]
        return CapabilityResult(capability=self.name, status=status, outcome=outcome, verified_steps=verified, reasoned_steps=reasoned, limitations=limitations).model_dump()

    def describe(self):
        return {"name": self.name, "title": self.title, "description": self.description, "profile": self.profile, "execution": "agent_loop"}


_CAPABILITIES = {item.name: item for item in (
    TurnCapability("tutor", "学习", "围绕资料与真实学习证据解释、练习和复习。", "tutor", "按真实学习证据推进；用户明确指定练习focus时优先遵守，若与当前知识点冲突先澄清，不得用不相关题卡冒充完成。遇到计算或代码结果需要验证，可建立解题计划并用受限Python校验；不要把推理说明称为已运行。"),
    TurnCapability("qa", "资料问答", "查询资料与学习状态，不写学习业务数据。", "qa", "只读业务问答。使用可追溯资料与真实状态，不承诺执行当前能力未授权的写入或代码。"),
    TurnCapability("research", "研究", "取证、研究报告与笔记。", "research", "研究优先取证，区分原始资料、公开网页与模型推断。工具失败要说明限制。"),
    TurnCapability("planner", "规划", "学习目标、课程规划和待确认变更。", "planner", "规划与变更基于已有资料和学习证据；已有路径必须经过精确预览和界面确认。"),
    TurnCapability("solve", "解题", "计划、执行、观察和校验的解题闭环。", "solve", "你正在执行solve能力。必须先solve_plan建立最多6步计划，目标保持用户原始问题；简单计算用1步，不为凑步骤拆分。可计算/代码步骤用method=python并调用python_check运行代码及至少一个具体检查，从真实stdout/错误中修正；受限Python不支持import、对象属性或自定义函数，使用变量、表达式、列表/字典、if/for和安全builtins。检查表达式可引用代码变量，expected是JSON值，不在表达式中使用assert。运行通过后用同一步骤的evidence_id调用solve_finish_step。概念步骤用method=reasoning并明确只是推理说明，不能标已执行。工具报错时修正，不能捏造执行结果。所有步骤完成后必须调用solve_finish。步骤explanation和最终summary用简短的学习者语言描述结果与校验范围；不展示evidence_id、步骤ID、计划版本、工具参数或内部状态名，不重复整份计划。最终回答优先两三句话给出结论与验证边界，界面已展示计划和执行记录，不再复述。不要输出模型私有思维链，只展示计划、必要推导、执行事实与结论。"),
)}


def get_capability(name="tutor"):
    try:
        return _CAPABILITIES[name]
    except KeyError:
        raise ValueError("未知 Agent 能力。") from None


def resolve_capability(profile=None, capability=None):
    selected = get_capability(capability or profile or "tutor")
    if profile is not None and selected.profile != profile:
        raise ValueError("capability 与 profile 不一致。")
    return selected


def capabilities():
    return [item.describe() for item in _CAPABILITIES.values()]
