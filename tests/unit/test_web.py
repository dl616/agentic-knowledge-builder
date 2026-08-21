"""网页摄取器的单元测试：验证正文抽取能去噪、保溯源。"""
from __future__ import annotations

from pke.agents.ingest.web import ingest_web

# 已知内容的 HTML：正文 + 广告 + 导航，断言抽取结果只含正文
SAMPLE_HTML = """\
<html>
<head><title>测试文章标题</title></head>
<body>
<nav><a href="/">首页</a> <a href="/about">关于</a></nav>
<div class="ad">【广告】限时抢购，点击立即购买！</div>
<article>
<h1>测试文章标题</h1>
<p>这是正文第一段，讲清楚一个真实的知识点。</p>
<p>这是正文第二段，包含具体的技术细节。</p>
</article>
<div class="related">相关推荐：另一篇毫不相干的文章</div>
<footer>版权信息</footer>
</body>
</html>
"""


def test_web_extracts_body_and_drops_noise(tmp_path):
    p = tmp_path / "article.html"
    p.write_text(SAMPLE_HTML, encoding="utf-8")

    doc = ingest_web(str(p))

    # 标题被正确识别
    assert doc.title == "测试文章标题"

    all_text = " ".join(c.text for c in doc.chunks)
    # 正文保留
    assert "正文第一段" in all_text
    assert "技术细节" in all_text
    # 噪声被剥离
    assert "广告" not in all_text
    assert "相关推荐" not in all_text
    assert "版权信息" not in all_text


def test_web_keeps_source_metadata(tmp_path):
    p = tmp_path / "article.html"
    p.write_text(SAMPLE_HTML, encoding="utf-8")

    doc = ingest_web(str(p))
    assert doc.source_type == "web"
    # 每个 chunk 都带 URL 溯源
    for c in doc.chunks:
        assert c.metadata["source"] == str(p)
        assert c.metadata["source_type"] == "web"
