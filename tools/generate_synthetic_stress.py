from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("data/stress/mineru")


def e(eid, page, typ, bbox, text="", confidence=0.98):
    return {"id": eid, "page": page, "type": typ, "bbox": bbox, "text": text, "confidence": confidence}


def write_case(path: Path, elements: list[dict], md: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "output.json").write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "output.md").write_text(md.strip() + "\n", encoding="utf-8")


def two_column_case(idx: int) -> tuple[list[dict], str]:
    elements = [
        e("s1", 1, "text", [0.06, 0.07, 0.42, 0.10], "一、选择题"),
        e("q1", 1, "text", [0.06, 0.13, 0.42, 0.16], "1. 下列计算正确的是（ ）"),
        e("q1a", 1, "text", [0.06, 0.17, 0.42, 0.20], "A. $1+1=3$"),
        e("q1b", 1, "text", [0.06, 0.21, 0.42, 0.24], "B. $2+2=4$"),
        e("q2", 1, "text", [0.06, 0.30, 0.42, 0.33], "2. 已知 $x=1$，求 $x+1$。"),
        e("q3", 1, "text", [0.56, 0.12, 0.92, 0.15], "3. 若 $a>b$，比较 $a+1$ 与 $b+1$。"),
        e("q4", 1, "text", [0.56, 0.22, 0.92, 0.25], "4. 如图，求三角形面积。"),
        e("img1", 1, "image", [0.62, 0.27, 0.84, 0.43], ""),
        e("q5", 1, "text", [0.56, 0.50, 0.92, 0.53], "5. 计算 $2^3$。"),
    ]
    md = """
一、选择题
1. 下列计算正确的是（ ）
A. $1+1=3$
B. $2+2=4$
2. 已知 $x=1$，求 $x+1$。
3. 若 $a>b$，比较 $a+1$ 与 $b+1$。
4. 如图，求三角形面积。
5. 计算 $2^3$。
参考答案
1. B
2. $2$
3. $a+1>b+1$
4. 略
5. $8$
"""
    return elements, md


def nested_section_case(idx: int) -> tuple[list[dict], str]:
    third_anchor = "3. 如图，求投影长度。" if idx == 5 else "1. 如图，求投影长度。"
    elements = [
        e("top1", 1, "text", [0.06, 0.06, 0.50, 0.09], "专题一 向量小题训练"),
        e("subA", 1, "text", [0.06, 0.11, 0.42, 0.14], "向量小题A"),
        e("q1a", 1, "text", [0.06, 0.16, 0.42, 0.19], "1. 已知 $\\vec a=(1,2)$，求模。"),
        e("q2a", 1, "text", [0.06, 0.23, 0.42, 0.26], "2. 判断两向量是否平行。"),
        e("subB", 1, "text", [0.06, 0.33, 0.42, 0.36], "向量小题B"),
        e("q1b", 1, "text", [0.06, 0.38, 0.42, 0.41], "1. 已知 $\\vec b=(2,4)$，求单位向量。"),
        e("q2b", 1, "text", [0.06, 0.45, 0.42, 0.48], "2. 计算 $\\vec a\\cdot\\vec b$。"),
        e("subC", 1, "text", [0.06, 0.55, 0.42, 0.58], "向量小题C"),
        e("q1c", 1, "text", [0.06, 0.60, 0.42, 0.63], third_anchor),
        e("img1", 1, "image", [0.12, 0.65, 0.36, 0.82], ""),
    ]
    md = f"""
专题一 向量小题训练
向量小题A
1. 已知 $\\vec a=(1,2)$，求模。
2. 判断两向量是否平行。
向量小题B
1. 已知 $\\vec b=(2,4)$，求单位向量。
2. 计算 $\\vec a\\cdot\\vec b$。
向量小题C
{third_anchor}
参考答案
1. 略
2. 略
"""
    return elements, md


def topic_set_case(idx: int) -> tuple[list[dict], str]:
    elements = [
        e("t1", 1, "text", [0.07, 0.06, 0.65, 0.09], f"模块{idx} 圆锥曲线题组"),
        e("g1", 1, "text", [0.07, 0.12, 0.50, 0.15], "题组A"),
        e("q1", 1, "text", [0.07, 0.18, 0.70, 0.21], "1. 已知椭圆焦点，求标准方程。"),
        e("q2", 1, "text", [0.07, 0.27, 0.70, 0.30], "2. 如图，直线与抛物线交于两点。"),
        e("img1", 1, "image", [0.18, 0.33, 0.58, 0.54], ""),
        e("g2", 2, "text", [0.07, 0.06, 0.50, 0.09], "题组B"),
        e("q1b", 2, "text", [0.07, 0.12, 0.70, 0.15], "1. 求双曲线离心率。"),
        e("q2b", 2, "text", [0.07, 0.22, 0.70, 0.25], "2. 证明弦长公式。"),
    ]
    md = """
模块 圆锥曲线题组
题组A
1. 已知椭圆焦点，求标准方程。
2. 如图，直线与抛物线交于两点。
题组B
1. 求双曲线离心率。
2. 证明弦长公式。
参考答案
1. 略
2. 略
"""
    return elements, md


def figure_heavy_case(idx: int) -> tuple[list[dict], str]:
    elements = [
        e("s1", 1, "text", [0.08, 0.06, 0.50, 0.09], "三、解答题"),
        e("q1", 1, "text", [0.08, 0.12, 0.72, 0.15], "1. 如图，在矩形 $ABCD$ 中，求阴影面积。"),
        e("img1", 1, "image", [0.16, 0.18, 0.58, 0.43], ""),
        e("q2", 1, "text", [0.08, 0.50, 0.72, 0.53], "2. 图中函数 $y=f(x)$ 的零点个数为多少？"),
        e("img2", 1, "image", [0.18, 0.56, 0.70, 0.82], ""),
        e("q3", 2, "text", [0.08, 0.08, 0.72, 0.11], "3. 如下表，求平均数。"),
        e("tab1", 2, "image", [0.14, 0.16, 0.72, 0.35], ""),
    ]
    md = """
三、解答题
1. 如图，在矩形 $ABCD$ 中，求阴影面积。
2. 图中函数 $y=f(x)$ 的零点个数为多少？
3. 如下表，求平均数。
参考答案
1. 略
2. 2
3. 略
"""
    return elements, md


def main() -> None:
    cases: list[tuple[str, int, callable]] = [
        ("two_column", 8, two_column_case),
        ("nested_section", 5, nested_section_case),
        ("topic_sets", 5, topic_set_case),
        ("figure_heavy", 2, figure_heavy_case),
    ]
    for category, count, factory in cases:
        for i in range(1, count + 1):
            prefix = {
                "two_column": "tc",
                "nested_section": "ns",
                "topic_sets": "ts",
                "figure_heavy": "fg",
            }[category]
            elements, md = factory(i)
            write_case(ROOT / category / f"{prefix}_{i:03d}", elements, md)

    readme = ROOT.parent / "README.md"
    readme.write_text(
        "Synthetic MinerU stress samples.\n\n"
        "- two_column: 8\n"
        "- nested_section: 5\n"
        "- topic_sets: 5\n"
        "- figure_heavy: 2\n\n"
        "These are not PDFs. They are deterministic MinerU-style output.json/output.md pairs.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
