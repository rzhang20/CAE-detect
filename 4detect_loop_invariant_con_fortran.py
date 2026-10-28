import os
import csv
import re

# ================= 配置区域 =================

INPUT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\elmerfem-3-2"
OUTPUT_CSV = os.path.join(INPUT_DIR, "loop_invariant_ranked_report.csv")

# 1. 过滤文件后缀：去掉 '.f'，因为 ElmerFEM 核心团队的现代代码全部是 .f90 / .F90
# 留下的都是现代自由格式 Fortran 和 C/C++ 核心文件
SOURCE_EXT = ('.c', '.cc', '.cpp', '.h',
              '.f90', '.F90', '.f95', '.F95', '.f03', '.f08')

# 2. 目录黑名单（雷区）：包含这些关键字的目录将被直接跳过（绝不扫描第三方数学库）
EXCLUDE_DIRS = [
    "mathlibs", "contrib", "umfpack", "hypre", "fhutiter",
    "lapack", "blas", "arpack", "amd", "tests", "matc"
]

# 3. 目录白名单（金矿）：只扫描路径中包含这些字符串的目录
# 设置为 ["fem/src", "elmergrid/src"] 可以精准定位 ElmerFEM 的核心物理场和网格处理逻辑
TARGET_DIRS = ["fem/src", "elmergrid/src"]

# 常见大型对象关键词（C++ + Fortran）
LARGE_OBJECT_KEYWORDS = [
    "Matrix", "Vector", "SparseMatrix", "BlockVector",
    "PETScVector", "FullMatrix", "LA::FullMatrix",
    "matrix", "vector", "real(", "double precision"
]

# 内存分配相关关键词（C++ + Fortran）
MEMORY_ALLOC_KEYWORDS = [
    "new ", " delete", "malloc", "calloc", "realloc",
    "make_shared", "make_unique", ".resize(", ".reserve(",
    "allocate(", "deallocate("
]

CONFIDENCE_THRESHOLD = 30

# ================= 正则表达式 =================

# C/C++ loop
CPP_LOOP_PATTERN = re.compile(r'\b(for|while)\b')
CPP_LOOP_VAR_PATTERN = re.compile(r'for\s*\(\s*(.*?)\s*;')

# Fortran loop
FORTRAN_LOOP_PATTERN = re.compile(r'^\s*do\s+', re.IGNORECASE)
FORTRAN_END_PATTERN = re.compile(r'^\s*end\s*do', re.IGNORECASE)
FORTRAN_LOOP_VAR_PATTERN = re.compile(r'do\s+(\w+)\s*=', re.IGNORECASE)

# ================= C/C++ 支持 =================

def extract_cpp_loop_var(line):
    m = CPP_LOOP_VAR_PATTERN.search(line)
    if not m:
        return None
    init = m.group(1)
    token = init.replace("++", "").replace("--", "")
    if '=' in token:
        parts = token.split('=')[0].strip().split()
        return parts[-1] if parts else None
    return None

# ================= Fortran 支持 =================

def extract_fortran_loop_var(line):
    m = FORTRAN_LOOP_VAR_PATTERN.search(line)
    if m:
        return m.group(1)
    return None

# ================= 评分系统 =================

def calculate_confidence(line, type_desc):

    kw_large = sum(1 for k in LARGE_OBJECT_KEYWORDS if k.lower() in line.lower())
    kw_mem = sum(1 for k in MEMORY_ALLOC_KEYWORDS if k.lower() in line.lower())

    score_kw = min(kw_large * 15 + kw_mem * 30, 60)

    score_base = 0
    if "[循环中内存分配]" in type_desc:
        score_base = 30
    elif "[大型对象构造]" in type_desc:
        score_base = 20
    elif "[函数调用]" in type_desc:
        score_base = 5
    elif "[Fortran循环不变]" in type_desc:
        score_base = 15

    total = score_kw + score_base
    return round(total, 2), kw_large + kw_mem


# ================= 主检测逻辑 =================

def detect_invariant_expressions(lines, file_path):
    results = []
    stack = []

    is_fortran = file_path.lower().endswith(
        ('.f', '.f90', '.f95', '.f03', '.f08')
    )

    for i, line in enumerate(lines):
        stripped = line.strip()

        # ---------- Fortran ----------
        if is_fortran:
            if FORTRAN_LOOP_PATTERN.search(stripped):
                loop_var = extract_fortran_loop_var(stripped)
                stack.append((i, loop_var))
                continue

            if stack:
                start_line, loop_var = stack[-1]

                if FORTRAN_END_PATTERN.search(stripped):
                    stack.pop()
                    continue

                if not stripped or stripped.startswith("!"):
                    continue

                if loop_var and re.search(rf'\b{loop_var}\b', stripped, re.IGNORECASE):
                    continue

                detection_type = None

                if any(k.lower() in stripped.lower() for k in MEMORY_ALLOC_KEYWORDS):
                    detection_type = "[循环中内存分配]"
                elif any(k.lower() in stripped.lower() for k in LARGE_OBJECT_KEYWORDS):
                    detection_type = "[大型对象构造]"
                elif "=" in stripped:
                    detection_type = "[Fortran循环不变赋值]"
                elif "(" in stripped and ")" in stripped:
                    detection_type = "[函数调用]"

                if detection_type:
                    confidence, kw_val = calculate_confidence(stripped, detection_type)

                    results.append({
                        "file": file_path,
                        "loop_start": start_line + 1,
                        "line_no": i + 1,
                        "type": detection_type,
                        "code": stripped,
                        "confidence": confidence,
                        "similarity": 0.0,
                        "keyword_count": kw_val
                    })

        # ---------- C/C++ ----------
        else:
            if CPP_LOOP_PATTERN.search(stripped):
                loop_var = extract_cpp_loop_var(stripped)
                stack.append((i, loop_var))
                continue

            if stack:
                start_line, loop_var = stack[-1]

                if "}" in stripped:
                    stack.pop()
                    continue

                if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                    continue

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
                        "similarity": 0.0,
                        "keyword_count": kw_val
                    })

    return results


# ================= 扫描与输出 =================

def scan_directory(input_dir):
    all_results = []
    file_id = 1

    print(f"正在扫描目录: {input_dir}")

    for root, dirs, files in os.walk(input_dir):
        # 1. 拦截黑名单目录：原地修改 dirs 列表，告诉 os.walk 不要进入这些雷区目录
        dirs[:] = [d for d in dirs if not any(excl.lower() in d.lower() for excl in EXCLUDE_DIRS)]

        # 2. 规范化路径分隔符，方便匹配
        norm_root = os.path.normpath(root).replace('\\', '/')

        # 3. 检查白名单：当前路径是否包含我们想要的核心目录？
        is_target_path = False
        if not TARGET_DIRS:
            is_target_path = True  # 如果没设置白名单，默认全扫
        else:
            if any(target in norm_root for target in TARGET_DIRS):
                is_target_path = True

        # 如果当前目录不在金矿范围内，直接跳过里面的文件
        if not is_target_path:
            continue

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

    print(f"发现在核心目录中存在潜在异味 {len(sorted_results)} 处，可信度 ≥ {CONFIDENCE_THRESHOLD} 的有 {len(filtered_results)} 处")

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