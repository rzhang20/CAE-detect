import os
import re
import csv
import pandas as pd

# ---------------------------
# 配置路径
# ---------------------------
base_dir = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"
output_csv = os.path.join(base_dir, "precision_loss_by_function_with_confidence.csv")
history_xlsx = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-精度丢失.xlsx"

# 支持的 C/C++ 文件扩展名
cpp_exts = {".cpp", ".cc", ".c", ".h", ".hpp"}

# ---------------------------
# 正则表达式
# ---------------------------
function_pattern = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_:<>]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*?\)\s*\{",
    re.DOTALL
)
float_decl_pattern = re.compile(r"\bfloat\b\s+([a-zA-Z_][a-zA-Z0-9_]*)")
real4_decl_pattern = re.compile(r"\bReal4\b\s*\*?\s*([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
float_sub_pattern = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*-\s*([a-zA-Z_][a-zA-Z0-9_]*)")
precision_output_pattern = re.compile(r"\b(std::cout|ofstream|std::ofstream)\b\s*<<")

# ---------------------------
# 读取历史精度丢失异味
# ---------------------------
def load_history_smells(xlsx_path):
    df = pd.read_excel(xlsx_path)
    smell_codes = []
    for _, row in df.iterrows():
        code = str(row.get("异味代码", "")).strip()
        if code:
            smell_codes.append(code)
    return smell_codes


history_smell_codes = load_history_smells(history_xlsx)

# ---------------------------
# 文本归一化 & 重合度计算
# ---------------------------
def normalize_code(text):
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"[^a-zA-Z_]", " ", text)
    return set(text.lower().split())


def compute_overlap_score(func_body, history_codes):
    func_tokens = normalize_code(func_body)
    if not func_tokens:
        return 0.0

    max_score = 0.0
    for hc in history_codes:
        hc_tokens = normalize_code(hc)
        if not hc_tokens:
            continue
        intersection = func_tokens & hc_tokens
        union = func_tokens | hc_tokens
        score = len(intersection) / len(union)
        max_score = max(max_score, score)

    return round(max_score, 3)

# ---------------------------
# 全局结果和 UID
# ---------------------------
results = []
uid = 1

# ---------------------------
# 函数分析
# ---------------------------
def analyze_function(func_name, func_body, file_path, start_lineno):
    float_vars = set()
    real4_vars = set()
    func_issues = set()
    problem_lines = []

    for i, raw_line in enumerate(func_body.split("\n")):
        line_no = start_lineno + i
        line = raw_line.strip()
        line_issues = []

        if line.startswith(("//", "/*", "*", "#include")):
            continue

        # float 声明
        for match in float_decl_pattern.finditer(line):
            float_vars.add(match.group(1))
            line_issues.append("float variable declared")

        # Real4 声明
        for match in real4_decl_pattern.finditer(line):
            real4_vars.add(match.group(1))
            line_issues.append("Real4 variable declared")

        # float 相减
        for match in float_sub_pattern.finditer(line):
            v1, v2 = match.group(1), match.group(2)
            if v1 in float_vars and v2 in float_vars:
                line_issues.append("float subtraction")

        # 流输出未设置精度
        if precision_output_pattern.search(line):
            context = "\n".join(func_body.split("\n")[max(0, i - 10):i + 1])
            if ".precision" not in context:
                line_issues.append("stream output no precision")

        # 时间相关输出
        if any(t in line for t in ["timeVector", "timestep", "times_and_names", "time"]):
            if ".precision" not in line:
                line_issues.append("time-related output no precision")

        if line_issues:
            func_issues.update(line_issues)
            problem_lines.append(
                f"第{line_no}行: {raw_line} 【问题：{' ; '.join(line_issues)}】"
            )

    if not func_issues:
        return None

    # ---------------------------
    # 可信度计算
    # ---------------------------
    rule_score = len(func_issues)
    overlap_score = compute_overlap_score(func_body, history_smell_codes)

    # 加权可信度（可解释）
    confidence_score = round(0.6 * rule_score + 0.4 * overlap_score * 10, 2)

    return {
        "file": os.path.relpath(file_path, base_dir),
        "function_name": func_name,
        "start_lineno": start_lineno,
        "problem_types": "; ".join(sorted(func_issues)),
        "problem_details": "\n".join(problem_lines),
        "rule_score": rule_score,
        "overlap_score": overlap_score,
        "confidence_score": confidence_score
    }

# ---------------------------
# 遍历文件
# ---------------------------
for root, _, files in os.walk(base_dir):
    for file in files:
        if os.path.splitext(file)[1] not in cpp_exts:
            continue

        file_path = os.path.join(root, file)
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
        except Exception as e:
            print(f"❌ 无法读取文件：{file_path}，原因：{e}")
            continue

        for match in function_pattern.finditer(file_content):
            func_name = match.group(2)
            start_lineno = file_content[:match.start()].count("\n") + 1

            brace_count = 1
            body_start = match.end()
            body_end = -1
            for pos in range(body_start, len(file_content)):
                if file_content[pos] == "{":
                    brace_count += 1
                elif file_content[pos] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        body_end = pos + 1
                        break

            if body_end == -1:
                continue

            func_body = file_content[match.start():body_end]
            result = analyze_function(func_name, func_body, file_path, start_lineno)

            if result:
                results.append([
                    uid,
                    result["file"],
                    result["function_name"],
                    result["start_lineno"],
                    len(result["problem_types"].split(";")),
                    result["rule_score"],
                    result["overlap_score"],
                    result["confidence_score"],
                    result["problem_types"],
                    result["problem_details"]
                ])
                uid += 1

# ---------------------------
# 按可信度排序并写 CSV
# ---------------------------
results.sort(key=lambda x: x[7], reverse=True)

with open(output_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "ID",
        "File",
        "FunctionName",
        "FunctionStartLine",
        "TotalProblemTypes",
        "RuleScore",
        "HistoryOverlapScore",
        "ConfidenceScore",
        "PrecisionLossIssues",
        "ProblemDetails" 
    ])
    writer.writerows(results)

print(f"\n✅ 完成：共检测出 {len(results)} 个函数存在潜在精度丢失问题")
print(f"📊 已按可信度排序，结果保存至：{output_csv}")
