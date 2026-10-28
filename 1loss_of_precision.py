import os
import re
import csv

# ---------------------------
# 配置路径
# ---------------------------
base_dir = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"
output_csv = os.path.join(base_dir, "precision_loss_by_function.csv")

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
# 全局结果和 UID
# ---------------------------
results = []
uid = 1  # 全局唯一 ID

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

        if line.startswith("//") or line.startswith("/*") or line.startswith("*") or line.startswith("#include"):
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
            var1, var2 = match.group(1), match.group(2)
            if var1 in float_vars and var2 in float_vars:
                line_issues.append("float subtraction")

        # 流输出未设置精度
        if precision_output_pattern.search(line):
            prev_context = "\n".join(func_body.split("\n")[max(0, i-10):i+1])
            if ".precision" not in prev_context:
                line_issues.append("stream output no precision")

        # 时间相关输出未设置精度
        if any(t in line for t in ["timeVector", "timestep", "times_and_names", "time"]):
            if ".precision" not in line:
                line_issues.append("time-related output no precision")

        if line_issues:
            func_issues.update(line_issues)
            problem_lines.append(f"第{line_no}行: {raw_line} 【问题：{' ; '.join(line_issues)}】")

    if func_issues:
        return {
            "file": os.path.relpath(file_path, base_dir),
            "function_name": func_name,
            "start_lineno": start_lineno,
            "problem_types": "; ".join(sorted(func_issues)),
            "problem_details": "\n".join(problem_lines)
        }
    return None

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

        # 提取函数
        for match in function_pattern.finditer(file_content):
            func_name = match.group(2)
            start_lineno = file_content[:match.start()].count("\n") + 1

            # 提取函数体（支持嵌套括号）
            brace_count = 1
            func_body_start = match.end()
            func_body_end = -1
            for pos in range(func_body_start, len(file_content)):
                if file_content[pos] == "{":
                    brace_count += 1
                elif file_content[pos] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        func_body_end = pos + 1
                        break
            if func_body_end == -1:
                print(f"⚠️ 函数 {func_name} 未找到闭合}}，跳过")
                continue

            func_body = file_content[match.start():func_body_end]

            # 分析函数
            func_result = analyze_function(func_name, func_body, file_path, start_lineno)
            if func_result:
                results.append([
                    uid,
                    func_result["file"],
                    func_result["function_name"],
                    func_result["start_lineno"],
                    len(func_result["problem_types"].split(";")),
                    func_result["problem_types"],
                    func_result["problem_details"]
                ])
                uid += 1  # 直接在这里更新，全局变量无需 global

# ---------------------------
# 写入 CSV
# ---------------------------
with open(output_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "ID", "File", "FunctionName", "FunctionStartLine",
        "TotalProblemTypes", "PrecisionLossIssues", "ProblemDetails"
    ])
    writer.writerows(results)

print(f"\n✅ 完成：共检测出 {len(results)} 个函数存在潜在精度丢失问题。结果保存在：{output_csv}")
