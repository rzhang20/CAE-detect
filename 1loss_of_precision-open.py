import os
import re
import csv
import difflib

# ---------------------------
# 配置路径
# ---------------------------
base_dir = r"C:\Users\dell\Desktop\检测的CAE项目\Kratos-3-1"
output_csv = os.path.join(base_dir, "precision_loss_ranked.csv")

# 支持的 C/C++ / Qt 文件扩展名
cpp_exts = {".cpp", ".cc", ".c", ".h", ".hpp"}

# Issue 提供的核心“嫌疑”上下文（用于相似度比对）
ISSUE_CONTEXT = """
Time is formatted with QString::number(); while StringHandler::number() is used for the variables.
Export data as CSV from OMEdit GUI, time column format reduced to 7 or 8 significant digits.
"""

# ---------------------------
# 正则表达式与权重
# ---------------------------
function_pattern = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_:<>]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*?\)\s*\{",
    re.DOTALL
)

# 异味特征正则
SMELL_PATTERNS = {
    "qstring_number": (re.compile(r"QString::number\s*\([^,)]*\)"), 40),  # 极高嫌疑（Issue直接点名）
    "float_decl": (re.compile(r"\bfloat\b"), 10),
    "csv_export": (re.compile(r"(csv|export|save|write|output)", re.I), 15),
    "time_context": (re.compile(r"(time|step|timestamp|res_res)", re.I), 15),
    "precision_loss": (re.compile(r"\.precision\(\s*[0-8]\s*\)"), 25),  # 设置精度过低
    "no_precision": (re.compile(r"<<.*(cout|ofstream)"), 10)  # 流输出但未见设置精度
}


# ---------------------------
# 计算相似度
# ---------------------------
def calculate_similarity(text):
    # 计算函数体与Issue描述的重合度
    return difflib.SequenceMatcher(None, ISSUE_CONTEXT.lower(), text.lower()).ratio() * 100


# ---------------------------
# 函数分析
# ---------------------------
def analyze_function(func_name, func_body, file_path, start_lineno):
    score = 0
    detected_smells = []

    # 1. 关键词权重计算
    for smell_name, (pattern, weight) in SMELL_PATTERNS.items():
        matches = pattern.findall(func_body)
        if matches:
            # 基础权重 + 匹配次数奖励(上限3次)
            score += weight + (min(len(matches), 3) * 2)
            detected_smells.append(smell_name)

    # 2. 文本相似度奖励
    sim_score = calculate_similarity(func_body)
    total_confidence = score + (sim_score * 0.5)  # 相似度占比

    # 3. 提取问题行位置
    problem_lines = []
    lines = func_body.split("\n")
    for i, line in enumerate(lines):
        if "QString::number" in line or "float" in line or "csv" in line.lower():
            problem_lines.append(f"L{start_lineno + i}: {line.strip()}")

    return {
        "confidence": round(total_confidence, 2),
        "smells": "; ".join(detected_smells),
        "details": " | ".join(problem_lines[:5])  # 仅保留前5处核心位置
    }


# ---------------------------
# 主遍历程序
# ---------------------------
results = []
print(f"🔍 正在扫描项目: {base_dir} ...")

for root, _, files in os.walk(base_dir):
    for file in files:
        if os.path.splitext(file)[1] not in cpp_exts:
            continue

        file_path = os.path.join(root, file)
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except:
            continue

        for match in function_pattern.finditer(content):
            func_name = match.group(2)
            start_pos = match.start()

            # 简单的括号匹配提取函数体
            brace_count = 0
            end_pos = -1
            for i in range(match.end() - 1, len(content)):
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break

            if end_pos == -1: continue

            func_body = content[start_pos:end_pos]
            start_lineno = content[:start_pos].count("\n") + 1

            analysis = analyze_function(func_name, func_body, file_path, start_lineno)

            # 阈值设置：Confidence > 30 认为是潜在异味
            if analysis["confidence"] > 30:
                results.append({
                    "File": os.path.relpath(file_path, base_dir),
                    "Function": func_name,
                    "Line": start_lineno,
                    "Confidence": analysis["confidence"],
                    "SmellTypes": analysis["smells"],
                    "CoreLocations": analysis["details"]
                })

# ---------------------------
# 排序与输出
# ---------------------------
# 按可信度从高到低排序
results.sort(key=lambda x: x["Confidence"], reverse=True)

with open(output_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["Confidence", "File", "Function", "Line", "SmellTypes", "CoreLocations"])
    writer.writeheader()
    writer.writerows(results)

print(f"\n✅ 检测完成！")
print(f"📊 发现 {len(results)} 处高风险精度丢失位置。")
print(f"📈 结果已按可信度降序排列，存至: {output_csv}")

if results:
    print("\n🔥 最高风险文件 Top 3:")
    for r in results[:3]:
        print(f"[{r['Confidence']}分] {r['File']} -> 函数: {r['Function']} (第{r['Line']}行)")