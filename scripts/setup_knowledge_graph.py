"""将外部知识图谱目录复制到项目内"""
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"D:\stock\knowledgeGraph"
DST = os.path.join(_ROOT, "knowledgeGraph")
EXCLUDE_DIRS = {"_archive", "_meta", "index"}  # 不需要入库的目录
EXCLUDE_FILES = {"node_index.md", "ontology.md"}  # 索引/本体类文件 (体积大但用途小)


def main():
    if not os.path.isdir(SRC):
        print(f"[ERROR] 源目录不存在: {SRC}")
        sys.exit(1)

    if os.path.exists(DST):
        print(f"[WARN] 目标已存在: {DST}")
        resp = input("覆盖? (yes/no): ").strip().lower()
        if resp != "yes":
            print("已取消")
            return
        shutil.rmtree(DST)

    print(f"复制 {SRC} → {DST}")
    print(f"排除目录: {EXCLUDE_DIRS}")
    print(f"排除文件: {EXCLUDE_FILES}")
    print()

    file_count = 0
    total_size = 0

    for root, dirs, files in os.walk(SRC):
        # 过滤排除目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        rel_root = os.path.relpath(root, SRC)
        target_dir = DST if rel_root == "." else os.path.join(DST, rel_root)
        os.makedirs(target_dir, exist_ok=True)

        for f in files:
            if f in EXCLUDE_FILES:
                continue
            src_path = os.path.join(root, f)
            dst_path = os.path.join(target_dir, f)
            size = os.path.getsize(src_path)
            shutil.copy2(src_path, dst_path)
            file_count += 1
            total_size += size

    print(f"[OK] 复制完成")
    print(f"  文件数: {file_count}")
    print(f"  总大小: {total_size / 1024:.1f} KB ({total_size / 1024 / 1024:.2f} MB)")
    print(f"  目标目录: {DST}")


if __name__ == "__main__":
    main()