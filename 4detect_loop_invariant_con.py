import os
import csv
import re

# ================= 配置区域 =================

INPUT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\9+26\Kratos-master"
OUTPUT_CSV = os.path.join(INPUT_DIR, "loop_invariant_ranked_report.csv")

SOURCE_EXT = ('.c', '.cc', '.cpp', '.h')

# 常见大型对象关键词
LARGE_OBJECT_KEYWORDS = [
    "Matrix", "Vector", "SparseMatrix", "BlockVector",
    "PETScVector", "FullMatrix", "LA::FullMatrix"
]

# 内存分配相关关键词（重点）
MEMORY_ALLOC_KEYWORDS = [
    "new ", " delete", "malloc", "calloc", "realloc",
    "make_shared", "make_unique", ".resize(", ".reserve("
]

LOOP_START_PATTERN = re.compile(r'\b(for|while)\b')
LOOP_VAR_PATTERN = re.compile(r'for\s*\(\s*(.*?)\s*;')

CONFIDENCE_THRESHOLD = 30

# ===========================================

def extract_loop_var(line):
    m = LOOP_VAR_PATTERN.search(line)
    if not m:
        return None
    init = m.group(1)
    token = init.replace("++", "").replace("--", "")
    if '=' in token:
        parts = token.split('=')[0].strip().split()
        return parts[-1] if parts else None
    return None


def calculate_confidence(line, type_desc):
    """
    基于关键词与类型的可信度评分（0-100）
    """

    kw_large = sum(1 for k in LARGE_OBJECT_KEYWORDS if k in line)
    kw_mem = sum(1 for k in MEMORY_ALLOC_KEYWORDS if k in line)

    # 关键词得分
    score_kw = min(kw_large * 15 + kw_mem * 30, 60)

    # 类型基础分
    score_base = 0
    if "[循环中内存分配]" in type_desc:
        score_base = 30
    elif "[大型对象构造]" in type_desc:
        score_base = 20
    elif "[函数调用]" in type_desc:
        score_base = 5

    total = score_kw + score_base
    return round(total, 2), kw_large + kw_mem


def detect_invariant_expressions(lines, file_path):
    results = []
    stack = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检测循环开始
        if LOOP_START_PATTERN.search(stripped):
            loop_var = extract_loop_var(stripped)
            stack.append((i, loop_var))
            continue

        if stack:
            start_line, loop_var = stack[-1]

            # 简单判断循环结束
            if "}" in stripped:
                stack.pop()
                continue

            if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                continue

            # 如果使用了循环变量，通常不是循环不变
            if loop_var and loop_var in stripped:
                continue

            detection_type = None

            if any(k in stripped for k in MEMORY_ALLOC_KEYWORDS):
                detection_type = "[循环中内存分配]"
            elif any(k in stripped for k in LARGE_OBJECT_KEYWORDS):
                detection_type = "[大型对象构造]"
            elif "(" in stripped and ")" in stripped and ";" in stripped and "=" not in stripped:
                detection_type = "[函数调用]"
            elif "=" in stripped and ";" in stripped:
                detection_type = "[可能的循环不变赋值]"

            if detection_type:
                confidence, kw_val = calculate_confidence(stripped, detection_type)

                results.append({
                    "file": file_path,
                    "loop_start": start_line + 1,
                    "line_no": i + 1,
                    "type": detection_type,
                    "code": stripped,
                    "confidence": confidence,
                    "similarity": 0.0,          # 保留字段，便于后续扩展
                    "keyword_count": kw_val
                })

    return results


def scan_directory(input_dir):
    all_results = []
    file_id = 1

    print(f"正在扫描目录: {input_dir}")

    for root, _, files in os.walk(input_dir):
        for name in files:
            if name.endswith(SOURCE_EXT):
                path = os.path.join(root, name)
                try:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    invariants = detect_invariant_expressions(lines, path)

                    for inv in invariants:
                        inv['id'] = file_id
                        all_results.append(inv)
                        file_id += 1

                except Exception as e:
                    print(f"处理文件失败: {path} ({e})")

    return all_results


def write_csv(results, output_file):
    sorted_results = sorted(results, key=lambda x: x['confidence'], reverse=True)
    filtered_results = [
        r for r in sorted_results if r['confidence'] >= CONFIDENCE_THRESHOLD
    ]

    print(f"发现潜在异味 {len(sorted_results)} 处，可信度 ≥ {CONFIDENCE_THRESHOLD} 的有 {len(filtered_results)} 处")

    if not filtered_results:
        return

    headers = [
        "id", "confidence", "type", "file",
        "line_no", "loop_start", "code",
        "similarity", "keyword_count"
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in filtered_results:
            writer.writerow({k: row[k] for k in headers})

    print(f"报告已生成: {output_file}")


if __name__ == "__main__":
    results = scan_directory(INPUT_DIR)
    write_csv(results, OUTPUT_CSV)
