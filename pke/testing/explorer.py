"""Explorer（探索器）：驱动浏览器抓取页面原始数据。

它回答一个问题：**「这个页面上，用户能看到什么、能操作什么？」**

为什么抓 A11y Tree（无障碍树），而不只抓 DOM（文档对象模型）？
    DOM 里有大量纯装饰的 div 嵌套、样式节点、脚本容器。改一次 CSS 重构，
    DOM 结构就天翻地覆，但用户能操作的东西一点没变——基于 DOM 的定位器会集体失效，
    这正是自动化测试维护成本高的根源。
    A11y Tree 只描述「有语义、可交互」的内容，对样式改版天然免疫。
    所以这里以 A11y Tree 为主、DOM 为辅，定位器也优先选 role / label 这类语义锚点。

关于主动探测（probe）的安全边界：
    不点提交类按钮（submit）——那会在真实站点上产生下单、发消息等不可逆副作用。
    只探测 type="button" 的按钮与上拉/勾选类控件，并记录「点击前后页面发生了什么」。
    这条边界是硬性的：探索器是只读的观察者，不是用户。
"""
from __future__ import annotations

from typing import Any

from ..agents.base import Agent, AgentMessage
from .schemas import Control, Interaction, Locator, PageSnapshot

# input 的 type 属性 → 控件类型（只有 input 需要看 type）
_INPUT_TYPE_MAP: dict[str, str] = {
    "password": "password",
    "checkbox": "checkbox",
    "radio": "radio",
    "file": "file",
    "submit": "button",
    "button": "button",
    "reset": "button",
}

# 非 input 标签 → 控件类型（与 type 无关，所以不能按 (标签, type) 组合判定——
# 真实页面的 <button> 几乎总是带 type="button" 或 type="submit"）
_TAG_MAP: dict[str, str] = {
    "textarea": "textarea",
    "select": "select",
    "button": "button",
    "a": "link",
}

# 角色映射：用于 role 策略定位（Playwright 的 get_by_role 需要 ARIA 角色名）
_ROLE_MAP: dict[str, str] = {
    "textbox": "textbox",
    "password": "textbox",
    "textarea": "textbox",
    "button": "button",
    "link": "link",
    "checkbox": "checkbox",
    "radio": "radio",
    "select": "combobox",
    "file": "button",
}


def infer_control_type(raw: dict[str, Any]) -> str:
    """从 HTML 标签与 type 推断归一化控件类型。

    input 看 type（password / checkbox / submit 各不相同）；
    其余标签只看标签名（button 无论 type 是 button 还是 submit，它就是个按钮）。
    """
    tag = str(raw.get("tag", "")).lower()
    input_type = str(raw.get("type", "")).lower()

    if tag == "input":
        # 除上表之外的 input（text / tel / email / number / 以及没写 type 的）都当文本框
        return _INPUT_TYPE_MAP.get(input_type, "textbox")
    if tag in _TAG_MAP:
        return _TAG_MAP[tag]
    # 带 ARIA 角色的自定义控件（div role="button" 之类）
    role = str(raw.get("role", "")).lower()
    if role in ("button", "link", "checkbox", "radio", "textbox"):
        return role
    return "unknown"


def choose_locator(raw: dict[str, Any], control_type: str) -> Locator:
    """按稳定性优先级挑选定位方式。

    优先级：testid > label > placeholder > role > text > css
    - testid（测试标识）是开发埋好的钩子，最稳，但可遇不可求。
    - label（关联标签文案）与用户看到的文字绑定，改样式不影响。
    - placeholder（占位符）次之，文案可能被产品改。
    - role / text 用于按钮与链接。
    - css 是最后兜底，最容易随改版失效。
    """
    testid = str(raw.get("testid", "")).strip()
    label = (str(raw.get("label_text", "")).strip() or str(raw.get("aria_label", "")).strip())
    placeholder = str(raw.get("placeholder", "")).strip()
    text = str(raw.get("text", "")).strip()

    if testid:
        return Locator(strategy="testid", value=testid)
    if label:
        return Locator(strategy="label", name=label)
    if placeholder:
        return Locator(strategy="placeholder", value=placeholder)
    if control_type in ("button", "link") and text:
        return Locator(strategy="role", role=_ROLE_MAP.get(control_type, "button"), name=text)
    if text:
        return Locator(strategy="text", value=text)

    element_id = str(raw.get("id", "")).strip()
    if element_id:
        return Locator(strategy="css", value=f"#{element_id}")
    return Locator(strategy="css", value=str(raw.get("tag", "div")).lower())


def choose_name(raw: dict[str, Any], control_type: str) -> str:
    """给控件起一个「人能看懂」的名字，用例里就引用这个名字。

    优先级：label > aria-label > placeholder > 相邻文本 > 可见文本 > name > id

    「相邻文本」为什么排在 placeholder 之后、可见文本之前：
    无 label 的表单里，placeholder 就是用户看到的字段名（最准）；
    而勾选框既没 label 也没 placeholder，只能靠旁边的说明文字认出它是协议框。
    """
    for key in ("label_text", "aria_label", "placeholder", "nearby_text", "text", "name", "id"):
        value = str(raw.get(key, "")).strip()
        if value:
            return value
    return f"未命名{control_type}"


def parse_controls(raw_items: list[dict[str, Any]]) -> list[Control]:
    """把浏览器里抽取到的原始元素信息转成 Control 列表（纯函数，可单测）。"""
    controls: list[Control] = []
    for raw in raw_items:
        control_type = infer_control_type(raw)
        if control_type == "unknown":
            continue
        controls.append(
            Control(
                name=choose_name(raw, control_type),
                control_type=control_type,
                locator=choose_locator(raw, control_type),
                text=str(raw.get("text", "")).strip(),
                required=bool(raw.get("required", False)),
                options=list(raw.get("options") or []),
                meta={
                    "tag": raw.get("tag", ""),
                    "input_type": raw.get("type", ""),
                    "id": raw.get("id", ""),
                    "name": raw.get("name", ""),
                    "nearby_text": str(raw.get("nearby_text", "")),
                    # 占位符与可见文本一并留存：主定位策略失效时，
                    # 执行层要靠它们做备选定位（自愈），丢了就没法降级。
                    "placeholder": str(raw.get("placeholder", "")),
                },
            )
        )
    return controls


# ---- 浏览器侧执行的 JS ----

# 抽取页面上的可交互元素（在浏览器里跑，返回结构化数据）
_EXTRACT_JS = """
() => {
  const visible = (el) => {
    if (el.type === 'hidden') return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0;
  };

  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) {
      const lab = document.querySelector(`label[for="${el.id}"]`);
      if (lab && lab.innerText) return lab.innerText.trim();
    }
    const parent = el.closest('label');
    if (parent && parent.innerText) return parent.innerText.trim();
    return '';
  };

  // 相邻文本：无 label 的勾选框/单选框，说明文字往往写在旁边的 <span> 或父容器里。
  // 少了这一步，改版成纯 placeholder 风格后，勾选框只能取到 value="on"，
  // 用例里就会出现「未勾选『on』时提交」这种没人看得懂的句子。
  const nearbyText = (el) => {
    // 只对勾选框/单选框生效：这类控件自己没有文案，说明必然写在旁边。
    // 对按钮不能这么干——按钮的父容器可能是整个 <form>，
    // 取回来是整个表单的文本（「手机号 验证码 密码 注册」），名字就废了。
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type !== 'checkbox' && type !== 'radio') return '';

    const parent = el.parentElement;
    if (parent) {
      const text = (parent.innerText || '').trim();
      if (text && text !== (el.value || '').trim()) return text.slice(0, 60);
    }
    const next = el.nextElementSibling;
    if (next && next.innerText) return next.innerText.trim().slice(0, 60);
    return '';
  };

  // 可见文本：勾选框没有 innerText，直接取 value 会得到 "on"，必须按类型区分
  const textOf = (el, tag) => {
    if (tag === 'input') {
      const t = (el.getAttribute('type') || '').toLowerCase();
      if (t === 'submit' || t === 'button' || t === 'reset') return (el.value || '').trim();
      return (el.innerText || '').trim();
    }
    return (el.innerText || '').trim();
  };

  const selector = 'input, textarea, select, button, a[href], [role="button"], [role="textbox"]';
  const out = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    out.push({
      tag: tag,
      type: (el.getAttribute('type') || '').toLowerCase(),
      id: el.id || '',
      name: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '',
      label_text: labelOf(el),
      nearby_text: nearbyText(el),
      text: textOf(el, tag).slice(0, 80),
      required: el.required === true || el.getAttribute('aria-required') === 'true',
      testid: el.getAttribute('data-testid') || '',
      role: el.getAttribute('role') || '',
      options: tag === 'select'
        ? Array.from(el.options).map((o) => o.text.trim()).filter(Boolean).slice(0, 20)
        : [],
    });
  }
  return out;
}
"""

# 精简 DOM：去掉脚本/样式/注释，只留结构骨架
_DOM_JS = """
() => {
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('script, style, noscript').forEach((n) => n.remove());
  return clone.outerHTML.replace(/\\s+/g, ' ').trim();
}
"""

# 读取提示区文本（用于判断操作后页面反馈了什么）
_ALERT_JS = """
() => {
  const nodes = document.querySelectorAll('[role="alert"], .message, .error, .tip');
  return Array.from(nodes).map((n) => n.innerText.trim()).filter(Boolean).join(' | ');
}
"""


class ExplorerAgent(Agent):
    """探索器 Agent：URL → PageSnapshot（页面快照）。

    probe       : 是否做主动探测（点击非提交类按钮，记录页面变化）。
                  默认 False，纯静态快照，绝对安全。
    max_probes  : 最多探测几个按钮，防止在大页面上跑太久。
    """

    name = "explorer"

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 15_000,
        probe: bool = False,
        max_probes: int = 5,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.probe = probe
        self.max_probes = max_probes

    @staticmethod
    def _playwright():
        """延迟导入 Playwright——它是可选依赖，没装时给出明确指引而不是崩溃。"""
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - 取决于运行环境
            raise RuntimeError(
                "未安装 Playwright。请先执行：pip install playwright && playwright install chromium"
            ) from exc
        return sync_playwright

    def run(self, msg: AgentMessage) -> AgentMessage:
        url = self._extract_url(msg.payload)
        snapshot = self.explore(url)
        return AgentMessage(
            payload=snapshot,
            meta={
                "agent": self.name,
                "url": url,
                "controls": snapshot.control_count,
                "interactions": len(snapshot.interactions),
            },
        )

    @staticmethod
    def _extract_url(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict) and payload.get("url"):
            return str(payload["url"])
        raise TypeError(f"Explorer 需要 URL 字符串或含 url 键的字典，收到 {type(payload).__name__}")

    def explore(self, url: str) -> PageSnapshot:
        """打开 URL 并采集快照（这是真正驱动浏览器的地方）。"""
        sync_playwright = self._playwright()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page()
                page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
                # 给前端框架一点渲染时间（SPA 常用），但不无限等待
                page.wait_for_timeout(300)

                raw_items = page.evaluate(_EXTRACT_JS)
                controls = parse_controls(raw_items)
                dom = str(page.evaluate(_DOM_JS))[:20_000]
                a11y_tree = self._capture_a11y_tree(page)
                title = page.title()

                interactions = (
                    self._probe_interactions(page, raw_items) if self.probe else []
                )
            finally:
                browser.close()

        return PageSnapshot(
            url=url,
            title=title,
            dom=dom,
            a11y_tree=a11y_tree,
            controls=controls,
            interactions=interactions,
            meta={"headless": self.headless, "probe": self.probe},
        )

    @staticmethod
    def _capture_a11y_tree(page: Any) -> str:
        """抓取无障碍树，优先用现代的 aria_snapshot，失败则回退旧 API。"""
        try:
            snapshot = page.locator("body").aria_snapshot()
            if snapshot:
                return str(snapshot)
        except Exception:  # noqa: BLE001 - 浏览器 API 版本差异，回退即可
            pass
        try:
            legacy = page.accessibility.snapshot()
            return ExplorerAgent._flatten_a11y(legacy)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _flatten_a11y(node: Any, depth: int = 0) -> str:
        """把旧版 accessibility 快照的嵌套结构摊平成可读文本。"""
        if not node or depth > 12:
            return ""
        lines: list[str] = []
        role = node.get("role", "")
        name = node.get("name", "")
        if role and role != "generic":
            lines.append(f"{'  ' * depth}- {role} {name!r}".rstrip())
        for child in node.get("children", []) or []:
            lines.append(ExplorerAgent._flatten_a11y(child, depth + 1))
        return "\n".join(line for line in lines if line)

    def _probe_interactions(self, page: Any, raw_items: list[dict[str, Any]]) -> list[Interaction]:
        """安全探测：只点非提交类按钮，记录操作前后的变化。

        提交类按钮（type=submit 或 form 内的 button）一概不碰，
        避免在真实业务站点上造成不可逆副作用。
        """
        interactions: list[Interaction] = []
        safe_buttons = [
            item
            for item in raw_items
            if str(item.get("tag", "")).lower() == "button"
            and str(item.get("type", "")).lower() in ("button", "")
        ][: self.max_probes]

        for item in safe_buttons:
            element_id = str(item.get("id", "")).strip()
            text = str(item.get("text", "")).strip() or element_id
            if not element_id:
                continue

            url_before = page.url
            alert_before = str(page.evaluate(_ALERT_JS))
            try:
                page.click(f"#{element_id}", timeout=3_000)
                page.wait_for_timeout(200)
            except Exception as exc:  # noqa: BLE001 - 探测失败不该中断整个探索
                interactions.append(
                    Interaction(
                        action="click",
                        target=text,
                        ok=False,
                        error=str(exc)[:200],
                        url_before=url_before,
                    )
                )
                continue

            alert_after = str(page.evaluate(_ALERT_JS))
            effect = ""
            if alert_after and alert_after != alert_before:
                effect = f"提示变化：{alert_after}"
            elif page.url != url_before:
                effect = f"跳转到 {page.url}"

            interactions.append(
                Interaction(
                    action="click",
                    target=text,
                    url_before=url_before,
                    url_after=page.url,
                    effect=effect,
                    ok=True,
                )
            )
        return interactions


__all__ = [
    "ExplorerAgent",
    "choose_locator",
    "choose_name",
    "infer_control_type",
    "parse_controls",
]
