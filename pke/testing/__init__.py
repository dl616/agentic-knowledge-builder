"""测试设计与知识工程（Web 测试方向）。

本项目从「通用知识库」升级为「智能测试设计系统」后新增的领域层：

- schemas  : 测试资产的数据契约（页面快照 / 页面模型 / 用例 / 失败报告）。
- explorer : Explorer（探索器）——驱动浏览器抓取页面原始数据。
- analyzer : Analyzer（分析器）——把瞬时快照提炼成可复用的 PageModel（页面对象模型）。

设计原则与全项目一致：Agent 是纯函数式的，输入 AgentMessage、输出 AgentMessage，
无隐藏副作用；数据契约显式声明，不靠字典猜。
"""
