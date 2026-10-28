import os
import csv
import re

# 单个文件路径
input_file = r"C:\Users\dell\Desktop\CAE项目-代码异味\31Nek5000-17.0\core\connect2-smell.f"
output_csv = os.path.join(os.path.dirname(input_file), "io_parallelism_smell.csv")

# 确保输出目录存在
os.makedirs(os.path.dirname(output_csv), exist_ok=True)

# 与大型数据读写相关的关键词
large_data_patterns = [
    r"\.re2", r"bin_rd1", r"read.*mesh", r"read.*curve", r"read.*bc",
    r"cbc", r"bc\(.*ifield", r"read.*flow", r"read.*field", r"read.*vel", r"read.*pressure",
    r"call\s+bin_rd1_mesh", r"call\s+bin_rd1_curve", r"call\s+bin_rd1_bc"
]

# 明确使用并行 I/O 的关键词
parallel_io_patterns = [
    r"MPI_File_(read|write)", r"byte_read_mpi", r"byte_open_mpi", r"byte_close_mpi",
    r"readp_re2_mesh", r"readp_re2_curve", r"readp_re2_bc",
    r"call\s+bcast", r"call\s+irecv", r"call\s+isend",
    r"#ifdef\s+MPIIO", r"#if\s+defined\s*\(\s*MPIIO\s*\)"
]

# 主进程串行 I/O 的关键词
serial_io_patterns = [
    r"if\s*\(\s*nid\s*==?\s*0\s*\)", r"if\s*\(\s*nio\s*==?\s*0\s*\)",
    r"write\s*\(6,", r"call\s+byte_close"
]

# 子程序识别正则
subroutine_re = re.compile(r"(?i)^\s*subroutine\s+(\w+)", re.MULTILINE)

# 文件名赋值正则
filename_var_pattern = re.compile(
    r'(?i)(re2fle)\s*=\s*["\']([^"\']+)["\']'
)

results = []


def extract_subroutines(code_lines):
    """提取所有子程序块 (名称, 起始行号, 子程序代码行列表)"""
    subroutines = []
    current = []
    name = None
    start_line = 0

    for i, line in enumerate(code_lines):
        match = subroutine_re.match(line)
        if match:
            if name and current:
                subroutines.append((name, start_line, current))
            name = match.group(1)
            start_line = i + 1
            current = [line]
        elif name:
            current.append(line)
    if name and current:
        subroutines.append((name, start_line, current))
    return subroutines


def find_filenames_in_code(lines, base_dir):
    """提取 Fortran 中文件名变量赋值"""
    filenames = set()
    for line in lines:
        m = filename_var_pattern.search(line)
        if m:
            var, fname = m.groups()
            fpath = fname
            if not os.path.isabs(fpath):
                fpath = os.path.normpath(os.path.join(base_dir, fpath))
            filenames.add(fpath)
    return filenames


# ========== 主检测逻辑 ==========
if os.path.isfile(input_file):
    try:
        with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        subs = extract_subroutines(lines)
        print(f"✅ 文件中共检测到 {len(subs)} 个子程序(subroutine)。")

        for sub_name, start_line, code in subs:
            code_text = "\n".join(code).lower()

            found_large_io = any(re.search(pat, code_text) for pat in large_data_patterns)
            found_parallel_io = any(re.search(pat, code_text) for pat in parallel_io_patterns)
            found_serial_io = any(re.search(pat, code_text) for pat in serial_io_patterns)

            filenames = find_filenames_in_code(code, os.path.dirname(input_file))
            large_files = []
            for fpath in filenames:
                if os.path.isfile(fpath):
                    size_kb = os.path.getsize(fpath) / 1024.0
                    if size_kb > 1:
                        large_files.append((fpath, size_kb))

            extra_warn = ""
            if large_files and not found_parallel_io:
                extra_warn = "且涉及文件大小 > 1KB，存在未并行I/O的风险。文件详情：" + \
                    ", ".join(f"{os.path.basename(f)}({size_kb:.1f}KB)" for f, size_kb in large_files)

            if found_large_io and not found_parallel_io and found_serial_io:
                results.append({
                    "file": input_file,
                    "line": start_line,
                    "reason": (
                        "函数中涉及大数据读取（如 .re2 网格、边界等）且存在主进程串行IO逻辑，"
                        "但未显式使用并行IO调用（如 readp_re2_mesh），可能引发性能瓶颈。"
                    ) + extra_warn,
                    "issue": f"函数 {sub_name} 存在大型数据读取但未并行化，建议使用 MPI-IO 等方式。"
                })

    except Exception as e:
        results.append({
            "file": input_file,
            "line": 0,
            "reason": "文件无法读取",
            "issue": str(e)
        })

# 写入 CSV
with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["file", "line", "reason", "issue"])
    writer.writeheader()
    for row in results:
        writer.writerow(row)

print(f"✅ 检测完成，共输出 {len(results)} 条结果。CSV 保存到：{output_csv}")
