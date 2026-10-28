import os
import re
import csv

# 输入路径
base_dir = r"C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27"

# 输出路径
output_div0_csv = os.path.join(base_dir, "division_by_zero.csv")
output_overuse_csv = os.path.join(base_dir, "division_overuse.csv")

cpp_exts = {".cpp", ".cc", ".c", ".h", ".hpp"}

# 除法过多判断阈值（占所有运算符比例）
threshold = 0.00  # 0%

# 运算符
operators = ["+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^", "<<", ">>", "="]

# 正则表达式
div_pattern = re.compile(r"/\s*[a-zA-Z_0-9(]")  # 检测除法
zero_like_pattern = re.compile(r"/\s*0\b|\b/0\.|/ *\(.*(zero|ZERO|Zero).*\)")  # 明显除以0、变量名含zero
loop_pattern = re.compile(r"\b(for|while)\b.*\(")

# 结果收集
div_by_zero_results = []
div_overuse_results = []
uid = 1

for root, _, files in os.walk(base_dir):
    for file in files:
        ext = os.path.splitext(file)[1]
        if ext not in cpp_exts:
            continue

        file_path = os.path.join(root, file)
        rel_path = os.path.relpath(file_path, base_dir)

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"❌ 无法读取文件：{file_path}，原因：{e}")
            continue

        op_counts = {op: 0 for op in operators}
        total_div_count = 0

        loop_level = 0  # 嵌套层数
        for i, line in enumerate(lines):
            lineno = i + 1
            stripped = line.strip()

            # 判断是否在循环中
            if loop_pattern.search(stripped):
                loop_level += 1
            if "{" in stripped:
                loop_level += stripped.count("{")
            if "}" in stripped:
                loop_level -= stripped.count("}")
                if loop_level < 0:
                    loop_level = 0

            # 检查除以0
            if div_pattern.search(stripped) and zero_like_pattern.search(stripped):
                div_by_zero_results.append([uid, rel_path, lineno, stripped])
                uid += 1

            # 运算符计数
            for op in operators:
                count = stripped.count(op)
                if op == "/" and loop_level > 0:
                    count *= (loop_level + 1)  # 简化权重处理：按嵌套层数加权
                op_counts[op] += count

        total_ops = sum(op_counts.values())
        div_ratio = op_counts["/"] / total_ops if total_ops > 0 else 0

        if div_ratio > threshold:
            div_overuse_results.append(
                [len(div_overuse_results) + 1, rel_path] +
                [op_counts[op] for op in operators] +
                [f"{div_ratio:.4f}"]
            )

# 写入除以0检测结果
with open(output_div0_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "File", "LineNumber", "Code"])
    writer.writerows(div_by_zero_results)

# 写入除法滥用检测结果
with open(output_overuse_csv, "w", newline='', encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "File"] + operators + ["Division Ratio"])
    writer.writerows(div_overuse_results)

print("✅ 检测完成！")
print(f"📄 除以0结果：{output_div0_csv}")
print(f"📄 除法滥用结果：{output_overuse_csv}")
