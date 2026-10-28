import os
import re
import csv
import difflib
import pandas as pd

# =========================================================
# 1. 路径配置
# =========================================================
base_dir = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"
excel_path = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-除法滥用.xlsx"

output_div0_csv = os.path.join(base_dir, "division_by_zero.csv")
output_overuse_csv = os.path.join(base_dir, "division_overuse_ranked.csv")

cpp_exts = {".cpp", ".cc", ".c", ".h", ".hpp"}

# =========================================================
# 2. 参数（排序而非过滤）
# =========================================================
TOP_N = 20

ALPHA = 0.3   # 除法强度
BETA  = 0.3   # 关键词
GAMMA = 0.4   # 历史相似度

KEYWORDS = [
    "normal", "norm", "denom", "denominator",
    "volume", "area", "jacobian", "det",
    "dt", "dx", "dy", "dz", "eps", "epsilon"
]

operators = ["+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^", "<<", ">>", "="]

# =========================================================
# 3. 正则
# =========================================================
comment_pattern = re.compile(
    r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
    re.DOTALL | re.MULTILINE
)

div_pattern = re.compile(r"/\s*[a-zA-Z_0-9(]")
zero_like_pattern = re.compile(r"/\s*0\b|\b/0\.|/ *\(.*(zero|ZERO|Zero).*\)")
loop_pattern = re.compile(r"\b(for|while)\b")

# =========================================================
# 4. 工具函数
# =========================================================
def remove_comments(text):
    def replacer(m):
        s = m.group(0)
        if s.startswith('/'):
            return " " + "\n" * s.count("\n")
        return s
    return re.sub(comment_pattern, replacer, text)

def similarity(source, snippet):
    if not snippet or len(snippet) < 5:
        return 0.0
    s = difflib.SequenceMatcher(None, source, snippet)
    m = s.find_longest_match(0, len(source), 0, len(snippet))
    return m.size / len(snippet)

# =========================================================
# 5. 读取历史异味
# =========================================================
smelly_snippets = []

print("⏳ 读取历史异味样本...")
if os.path.exists(excel_path):
    df = pd.read_excel(excel_path)
    col = next((c for c in df.columns if "异味代码" in str(c)), None)
    if col:
        smelly_snippets = df[col].dropna().astype(str).tolist()
        print(f"✅ 已加载 {len(smelly_snippets)} 条历史异味")
    else:
        print("⚠️ Excel 中未找到“异味代码”列")
else:
    print("⚠️ 未找到 Excel 文件")

# =========================================================
# 6. 主扫描
# =========================================================
div0_results = []
overuse_results = []

uid_div0 = 1

print("⏳ 扫描项目源码...")

for root, _, files in os.walk(base_dir):
    for file in files:
        if os.path.splitext(file)[1] not in cpp_exts:
            continue

        path = os.path.join(root, file)
        rel_path = os.path.relpath(path, base_dir)

        try:
            raw = open(path, encoding="utf-8", errors="ignore").read()
        except:
            continue

        clean = remove_comments(raw)
        lines = clean.splitlines()

        op_counts = {op: 0 for op in operators}
        loop_divs = []
        loop_level = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue

            if loop_pattern.search(stripped):
                loop_level += 1
            loop_level += stripped.count("{")
            loop_level -= stripped.count("}")
            loop_level = max(loop_level, 0)

            if div_pattern.search(stripped) and zero_like_pattern.search(stripped):
                div0_results.append([uid_div0, rel_path, i, stripped])
                uid_div0 += 1

            for op in operators:
                op_counts[op] += stripped.count(op)

            if div_pattern.search(stripped) and loop_level > 0:
                weight = loop_level + 1
                loop_divs.append((i, stripped, weight))

        if op_counts["/"] == 0:
            continue   # 唯一硬过滤：文件里至少出现过 /

        total_ops = sum(op_counts.values())
        div_ratio = op_counts["/"] / total_ops if total_ops else 0

        # ---------- 除法强度得分 ----------
        div_score = min(div_ratio / 0.01, 1.0)

        # ---------- 关键词得分 ----------
        keyword_hits = 0
        for _, code, _ in loop_divs:
            low = code.lower()
            keyword_hits += sum(1 for k in KEYWORDS if k in low)
        keyword_score = min(keyword_hits / 5, 1.0)

        # ---------- 历史相似度 ----------
        sim_score = 0.0
        for s in smelly_snippets:
            sim_score = max(sim_score, similarity(clean, s))

        confidence = (
            ALPHA * div_score +
            BETA  * keyword_score +
            GAMMA * sim_score
        )

        core = sorted(loop_divs, key=lambda x: x[2], reverse=True)[:5]
        core_desc = "; ".join(f"L{l}(w={w}): {c}" for l, c, w in core)

        overuse_results.append({
            "ID": 0,
            "File": rel_path,
            "Confidence": round(confidence, 4),
            "Div Ratio": f"{div_ratio:.4f}",
            "Keyword Hits": keyword_hits,
            "Similarity": round(sim_score, 4),
            **op_counts,
            "Core Smell Locations": core_desc
        })

# =========================================================
# 7. 排序 & 输出
# =========================================================
overuse_results.sort(key=lambda x: x["Confidence"], reverse=True)
overuse_results = overuse_results[:TOP_N]

for i, r in enumerate(overuse_results):
    r["ID"] = i + 1

with open(output_div0_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "File", "Line", "Code"])
    writer.writerows(div0_results)

headers = list(overuse_results[0].keys()) if overuse_results else []
with open(output_overuse_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    writer.writerows(overuse_results)

print("✅ 检测完成")
print(f"📄 除以0结果: {output_div0_csv}")
print(f"📄 除法滥用 Top-{TOP_N}: {output_overuse_csv}")
