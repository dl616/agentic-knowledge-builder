"""Agent 抽象基类与统一接口。

定义「Agent」的契约：所有 Agent 都是纯函数式的——
输入一个 AgentMessage，输出一个 AgentMessage，无隐藏副作用。

协同模式是 Orchestrator-Worker：
- Orchestrator（总控）负责识别、规划、调度。
- 专项 Agent（Worker）各干一类活，不直接互相调用。
- 通过统一契约通信，每个 Agent 可独立测试、可插拔扩展。

新增 Agent = 继承 Agent + 注册到 Orchestrator 的注册表，不修改已有代码。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMessage:
    """Agent 之间通信的统一消息体。

    payload : 消息载荷（可以是 Document、查询、chunk 列表……，取决于上下文）。
    meta    : 附加信息（来源、阶段、置信度、错误信息……）。
    """

    payload: Any
    meta: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """所有 Agent 的抽象基类。

    子类必须实现：
    - name  : 唯一标识（注册表按它索引）。
    - run   : 核心逻辑，输入/输出都是 AgentMessage。
    """

    name: str

    @abstractmethod
    def run(self, msg: AgentMessage) -> AgentMessage:
        """执行本 Agent 的职责，返回处理后的消息。"""
        ...
