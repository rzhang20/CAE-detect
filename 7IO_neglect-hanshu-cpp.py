import os
import csv
import re

CPP_EXT = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}

# ========== 1. 大数据读写模式 ==========
large_io_patterns = [
    r"\.mesh", r"\.vtk", r"\.vtu", r"\.pvtu", r"\.hdf5?", r"\.nc",
    r"\.dat", r"\.out", r"\.inp", r"\.prm", r"\.bin"
]

# 匹配类似 "filename = 'mesh.vtk'" 或 ifstream("mesh.vtk")
file_detection_patterns = [
    r'["\']([^"\']+\.(mesh|vtk|vtu|pvtu|hdf5?|dat|out|inp|prm|bin|nc))["\']',
    r'(\w+)\s*=\s*["\']([^"\']+\.(mesh|vtk|vtu|pvtu|hdf5?|dat|out|inp|prm|bin|nc))["\']'
]

# ========== 2. 串行 IO 模式 ==========
serial_io_patterns = [
    r"\bstd::ifstream\b",
    r"\bstd::ofstream\b",
    r"\bfopen\s*\(",
    r"\bfread\s*\(",
    r"\bfwrite\s*\(",
    r"\bfprintf\s*\(",
    r"\bifstream\s*\(",
    r"\bofstream\s*\(",
]

# ========== 3. 并行 IO 模式 ==========
parallel_io_patterns = [
    r"\bMPI_File_read\b",
    r"\bMPI_File_write\b",
    r"\bMPI_File_open\b",
    r"\bMPI_File_close\b",
    r"parallel::distributed::SolutionTransfer",
    r"parallel::distributed::Triangulation",
    r"H5Pset_fapl_mpio",
    r"H5Dwrite",
    r"H5Dread",
    r"p4est",
]

# ========== 4. MPI Rank 判断（串行 I/O 常见写法） ==========
rank0_patterns = [
    r"if\s*\(\s*rank\s*==\s*0\s*\)",
    r"if\s*\(\s*(mpi_rank|this_mpi_process)\s*==\s*0\s*\)",
]

# ========== 主检测函数 ==========
def analyze_cpp_file(file_path):
    results = []
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        code = f.read()
        lines = code.splitlines()

    code_lower = code.lower()

    # 是否检测到大文件路径
    large_file_found = any(re.search(pat, code_lower) for pat in large_io_patterns)

    # 是否使用了串行 IO
    serial_io_found = any(re.search(pat, code) for pat in serial_io_patterns)

    # 是否使用并行 IO
    parallel_io_found = any(re.search(pat, code) for pat in parallel_io_patterns)

    # 是否 rank 0 读文件
    rank0_serial_io = any(re.search(pat, code) for pat in rank0_patterns)

    # 提取出现的大文件名（用于输出）
    file_occurrences = []
    for pat in file_detection_patterns:
        for m in re.finditer(pat, code):
            if isinstance(m.group(0), str):
                file_occurrences.append(m.group(0))

    # ----------- 检测不满足并行 IO 的情形 -----------
    if large_file_found and serial_io_found and not parallel_io_found:
        results.append({
            "file": file_path,
            "line": 0,
            "reason": (
                "发现大型数据文件读写（如 mesh/vtk/prm 等），且使用串行 IO（ifstream/ofstream/fopen），"
                "但未检测到并行 I/O（MPI-IO/HDF5 parallel/p4est IO）。"
            ),
            "issue": "可能存在 IO 性能瓶颈，建议使用分布式读写或 MPI-IO。"
        })

    # ----------- rank 0 读文件再广播（常见性能坏味道） -----------
    if large_file_found and rank0_serial_io and not parallel_io_found:
        results.append({
            "file": file_path,
            "line": 0,
            "reason": (
                "检测到大型文件由 rank 0 读取（if(rank==0)），其余进程通过广播/复制获得，"
                "这在大规模并行计算中可能造成 IO 瓶颈。"
            ),
            "issue": "建议使用 p4est / MPI-IO / HDF5 并行方式避免单核读IO。"
        })

    return results


# ========== 遍历目录 ==========
def analyze_cpp_project(root_dir):
    all_results = []
    for root, _, files in os.walk(root_dir):
        for name in files:
            if any(name.lower().endswith(ext) for ext in CPP_EXT):
                path = os.path.join(root, name)
                all_results.extend(analyze_cpp_file(path))
    return all_results


# ========== 写 CSV ==========
def write_csv(results, csv_path):
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "line", "reason", "issue"])
        writer.writeheader()
        writer.writerows(results)


# ========== 主执行入口 ==========
if __name__ == "__main__":
    project_dir = r"C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27"
    output_csv = os.path.join(project_dir, "cpp_io_smell_report.csv")

    results = analyze_cpp_project(project_dir)
    write_csv(results, output_csv)

    print(f"✅ 检测完成，共输出 {len(results)} 条可能的 IO 异味。")
    print(f"📄 CSV 已保存：{output_csv}")
