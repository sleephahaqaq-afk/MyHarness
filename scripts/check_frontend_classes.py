"""核对 TSX 里用到的 class 与 CSS 里定义的 class 是否一一对应。

Headless Chrome 在这台机器上起不来（被拦），所以用静态核对兜住"类名拼错 /
样式漏定义"这类会直接破坏布局的问题。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"

css = (ROOT / "styles" / "app.css").read_text(encoding="utf-8")
css += (ROOT / "styles" / "tokens.css").read_text(encoding="utf-8")
defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))

used = set()
for tsx in list(ROOT.glob("*.tsx")) + list(ROOT.glob("components/*.tsx")):
    text = tsx.read_text(encoding="utf-8")
    for match in re.finditer(r'className=(?:"([^"]*)"|\{`([^`]*)`\})', text):
        raw = match.group(1) or match.group(2) or ""
        # 去掉 ${...} 插值，只留静态 token
        raw = re.sub(r"\$\{[^}]*\}", " ", raw)
        for token in raw.split():
            if re.fullmatch(r"[a-zA-Z][\w-]*", token):
                used.add(token)

# 动态拼接出来的类名（phase 状态、role 等）
dynamic = {
    "planning", "executing", "reviewing", "result",
    "done", "current", "active", "todo", "running", "error",
    "semantic", "episodic", "procedural", "is-active",
}

missing = sorted(used - defined)
print(f"CSS 定义: {len(defined)} 个类")
print(f"TSX 使用: {len(used)} 个类")
print(f"未在 CSS 中找到: {missing or '无'}")
unused_dynamic = sorted(d for d in dynamic if d not in defined)
print(f"动态类缺失: {unused_dynamic or '无'}")
raise SystemExit(1 if missing else 0)
