#!/usr/bin/env python3
"""作品集资讯库构建脚本：读取 data.json，校验后写回 index.html 内嵌数据。
用法：python3 build.py

insights.json 若存在则保留在磁盘上，但不再校验、内嵌或展示。
"""
import base64, io, json, re, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTES_DIR = HERE.parent  # /workspace/shen/资讯/

# 一级（tab）固定顺序
TABS = ["简历", "作品集", "招聘信息", "作品集简历合集"]

# 二级（category）按一级约束；空桶构建时允许（页面不展示），但值必须在此枚举内
CATEGORIES = {
    "简历": {"AI产品设计简历", "产品设计简历", "设计工程师简历", "简历指南"},
    "作品集": {"AI设计作品集", "产品设计作品集", "设计工程师作品集", "作品集指南"},
    "招聘信息": {"岗位趋势", "招聘信号", "观点"},
    "作品集简历合集": {"国外目录站", "国内目录站", "开源GitHub", "媒体社区"},
}

ENUMS = {
    "platform": {"个人站", "Behance", "Dribbble", "YouTube", "X", "文章", "目录站", "指南", "站酷"},
    "track": {"设计工程师", "产品设计", "AI设计", "通用"},
    "type": {"作品集示例", "指南文章", "招聘信号", "观点", "目录"},
    "verified": {"已核", "未核链"},
    "tab": set(TABS),
}
REQUIRED = ["id", "title", "url", "platform", "track", "type", "verified", "why", "tags", "added", "source_note", "tab", "category"]


def fail(msg):
    print("✗ " + msg)
    sys.exit(1)


def load(name):
    try:
        return json.loads((HERE / name).read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"{name} 解析失败：{e}")


def validate(data):
    notes_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(NOTES_DIR.glob("*.md")))
    ids, urls, errs, warns = set(), set(), [], []
    for i, d in enumerate(data):
        tag = d.get("id", f"#{i}")
        for k in REQUIRED:
            if k not in d or d[k] in ("", None, []):
                errs.append(f"{tag}: 缺少字段 {k}")
        for k, allowed in ENUMS.items():
            if d.get(k) not in allowed:
                errs.append(f"{tag}: {k}={d.get(k)!r} 不在 {sorted(allowed)}")
        tab = d.get("tab")
        cat = d.get("category")
        if tab in CATEGORIES and cat not in CATEGORIES[tab]:
            errs.append(f"{tag}: category={cat!r} 不属于 tab={tab!r}（允许：{sorted(CATEGORIES[tab])}）")
        if not isinstance(d.get("tags"), list):
            errs.append(f"{tag}: tags 必须是数组")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d.get("added", ""))):
            errs.append(f"{tag}: added 需为 YYYY-MM-DD")
        if d.get("id") in ids:
            errs.append(f"{tag}: id 重复")
        ids.add(d.get("id"))
        u = (d.get("url") or "").strip()
        if u in urls:
            errs.append(f"{tag}: url 重复 {u}")
        urls.add(u)
        if u and u not in notes_text:
            errs.append(f"{tag}: url 未出现在 {NOTES_DIR} 的任何 .md 笔记中 → {u}")
        cov = d.get("cover")  # 可选：封面相对 site 目录，缺省时页面显示占位
        if cov and not (HERE / cov).is_file():
            warns.append(f"{tag}: cover 文件不存在 {cov}（页面将显示占位）")
        for src in str(d.get("source_note", "")).split("；"):
            if src and not (NOTES_DIR / src).exists():
                errs.append(f"{tag}: source_note 找不到文件 {src}")
    for w in warns:
        print("! " + w)
    if errs:
        fail("校验未通过：\n  " + "\n  ".join(errs))


COVER_MAX_SIDE = 800   # 内嵌前再压一次：长边上限
COVER_QUALITY = 65


def cover_data_url(path):
    """把本地封面压缩后转成 data:image/jpeg;base64,...，失败返回 None（页面回退 ./covers/）"""
    try:
        from PIL import Image
        im = Image.open(path)
        im = im.convert("RGB")
        im.thumbnail((COVER_MAX_SIDE, COVER_MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=COVER_QUALITY, optimize=True, progressive=True)
        raw = buf.getvalue()
    except Exception as e:
        print(f"! 封面压缩失败 {path.name}（{e}），直接内嵌原图")
        try:
            raw = path.read_bytes()
        except Exception:
            return None
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def with_cover_data(data):
    """返回带 cover_data 的副本，只写进 index.html，不回写 data.json（保留 cover 相对路径便于维护）"""
    out, n = [], 0
    for d in data:
        d = dict(d)
        cov = d.get("cover")
        if cov and (HERE / cov).is_file():
            url = cover_data_url(HERE / cov)
            if url:
                d["cover_data"] = url
                n += 1
        out.append(d)
    return out, n


def embed(obj):
    # 防止 </script> 截断：把 < > & 转成 \u 转义，JSON.parse / json.loads 都能还原
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def replace_block(html, marker, script_id, payload):
    pat = re.compile(rf"(<!-- {marker}:BEGIN -->).*?(<!-- {marker}:END -->)", re.S)
    if not pat.search(html):
        fail(f"index.html 缺少 <!-- {marker}:BEGIN/END --> 标记")
    block = f'\n<script type="application/json" id="{script_id}">{payload}</script>\n'
    return pat.sub(lambda m: m.group(1) + block + m.group(2), html, count=1)


def main():
    data = load("data.json")
    validate(data)
    html_path = HERE / "index.html"
    html = html_path.read_text(encoding="utf-8")
    embedded, n_cov = with_cover_data(data)
    html = replace_block(html, "DATA", "data-json", embed(embedded))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = re.sub(r'<meta name="build-time" content="[^"]*">', f'<meta name="build-time" content="{stamp}">', html)
    html_path.write_text(html, encoding="utf-8")

    by_tab = {}
    for d in data:
        by_tab[d["tab"]] = by_tab.get(d["tab"], 0) + 1
    unv = sum(d["verified"] != "已核" for d in data)
    tab_str = "，".join(f"{k} {by_tab.get(k, 0)}" for k in TABS)
    print(f"✓ 构建完成 {html_path}（{html_path.stat().st_size/1024/1024:.2f} MB，内嵌封面 {n_cov} 张）")
    print(f"  条目 {len(data)}（{tab_str}）· 未核链 {unv} · 最后更新 {max(d['added'] for d in data)}")


if __name__ == "__main__":
    main()
