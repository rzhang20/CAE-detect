import os
import csv
import re

INPUT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27"

SOURCE_EXT = ('.c', '.cc', '.cpp', '.h')

# 常见大型对象关键词（你原来的）
LARGE_OBJECT_KEYWORDS = [
    "Matrix", "Vector", "SparseMatrix", "BlockVector",
    "PETScVector", "FullMatrix", "LA::FullMatrix"
]

# 循环关键词
LOOP_START_PATTERN = re.compile(r'\b(for|while)\b')
LOOP_VAR_PATTERN = re.compile(r'for\s*\(\s*(.*?)\s*;')  # 提取for循环初始化部分


def extract_loop_var(line):
    """从 for(int i=0;...) 提取循环变量 i"""
    m = LOOP_VAR_PATTERN.search(line)
    if not m:
        return None
    init = m.group(1)
    token = init.replace("++", "").replace("--", "")
    if '=' in token:
        return token.split('=')[0].strip()
    return None


def detect_invariant_expressions(lines):
    results = []
    stack = []  # 记录循环开始的行号

    for i, line in enumerate(lines):
        stripped = line.strip()

        # ---------------------------
        # 判断当前行是否为循环开始
        # ---------------------------
        if LOOP_START_PATTERN.search(stripped):
            loop_var = extract_loop_var(stripped)
            stack.append((i, loop_var))
            continue

        # ---------------------------
        # 仍在循环内部
        # ---------------------------
        if stack:
            start_line, loop_var = stack[-1]

            # 循环结束
            if "}" in stripped:
                stack.pop()
                continue

            # 跳过空行
            if not stripped or stripped.startswith("//"):
                continue

            # -----------------------------------------
            # 检测循环不变计算模式：
            # 1. 不包含循环变量
            # 2. 是一次性构造 / 赋值 / 函数调用
            # -----------------------------------------
            if loop_var and loop_var in stripped:
                continue  # 使用循环变量 → 不可能是不变计算

            # 大型对象构造
            if any(k in stripped for k in LARGE_OBJECT_KEYWORDS):
                results.append((start_line + 1, i + 1, "[大型对象构造]", stripped))
                continue

            # 函数调用
            if "(" in stripped and ")" in stripped and ";" in stripped:
                results.append((start_line + 1, i + 1, "[函数调用]", stripped))
                continue

            # 赋值语句
            if "=" in stripped and ";" in stripped:
                results.append((start_line + 1, i + 1, "[可能的循环不变赋值]", stripped))
                continue

    return results


def analyze_file(filepath):
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return detect_invariant_expressions(lines)


def scan_directory(input_dir):
    all_results = []
    file_id = 1

    for root, _, files in os.walk(input_dir):
        for name in files:
            if name.endswith(SOURCE_EXT):
                path = os.path.join(root, name)
                invariants = analyze_file(path)

                if not invariants:
                    continue

                for start, end, typ, code in invariants:
                    all_results.append({
                        "id": file_id,
                        "file": path,
                        "loop_start": start,
                        "line": end,
                        "type": typ,
                        "code": code
                    })
                    file_id += 1
    return all_results


def write_csv(results, output_file):
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "file", "loop_start", "line", "type", "code"]
        )
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    results = scan_directory(INPUT_DIR)
    output_csv = os.path.join(INPUT_DIR, "loop_invariant_simple_report.csv")
    write_csv(results, output_csv)
    print("检测完成，报告生成：", output_csv)
