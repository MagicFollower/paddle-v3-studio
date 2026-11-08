"""合同号识别判据：合成数据覆盖七个开关与边界，退出码=失败条数。

用法：
  .venv\\Scripts\\python.exe scripts\\check_contract_no.py            # 正常判据
  .venv\\Scripts\\python.exe scripts\\check_contract_no.py --selftest # 注入缺陷证明判据会红
不依赖模型/服务，纯逻辑校验，可快速复跑。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
import contract as ct  # noqa: E402

RESULTS = []


def L(t, c=0.99):
    return {"text": t, "bbox": [0, 0, 1, 1], "bboxNorm": [0, 0, 1, 1], "confidence": c}


def pg(n, *lines):
    return {"page": n, "ocr": list(lines)}


def check(name, ok):
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


def fno(r):
    return (r.get("found") or {}).get("number")


def fsrc(r):
    return (r.get("found") or {}).get("source")


def fraw(r):
    return (r.get("found") or {}).get("numberRaw")


def cp(r):
    return r.get("crossPage") or {}


def run_suite():
    # 单行 / 多行 / 折行
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001"))])
    check("单行匹配", fno(r) == "HT-2026-001" and fsrc(r) == "same-line")
    r = ct.extract_contract_no([pg(1, L("合同编号："), L("HT-2026-001"))])
    check("多行-下行", fno(r) == "HT-2026-001" and fsrc(r) == "next-line")
    r = ct.extract_contract_no([pg(1, L("合同编号："), L("HT-2026-"), L("001"))])
    check("多行-折行", fno(r) == "HT-2026-001" and fsrc(r) == "split-line")
    # 开关独立关闭
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001"))], {"match_single_line": False, "match_multi_line": False})
    check("单行+多行关→无命中", fno(r) is None)
    r = ct.extract_contract_no([pg(1, L("合同编号："), L("HT-2026-001"))], {"match_multi_line": False})
    check("多行关→下行不命中", fno(r) is None)
    # 跨页一致 / 不一致 / 多数投票
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001")), pg(2, L("合同号 HT-2026-001"))])
    check("跨页一致", cp(r).get("consistent") is True and cp(r).get("occurrenceCount") == 2 and cp(r).get("pages") == [1, 2])
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001")), pg(2, L("合同编号：HT-2026-002"))])
    check("跨页不一致", cp(r).get("consistent") is False and len(cp(r).get("distinctNumbers", [])) == 2)
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-002")), pg(2, L("合同编号：HT-2026-001")), pg(3, L("合同编号：HT-2026-001"))])
    check("多数投票", fno(r) == "HT-2026-001" and cp(r).get("chosenBy") == "majority")
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-002")), pg(2, L("合同编号：HT-2026-001"))], {"cross_page_check": False})
    check("跨页关取首个", fno(r) == "HT-2026-002" and cp(r).get("consistent") is None)
    # 置信度过滤
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001", 0.3))])
    check("低置信过滤", fno(r) is None and cp(r).get("filtered", {}).get("confidence") == 1)
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001", 0.99))], {"min_no_confidence": 0.6})
    check("高置信保留", fno(r) == "HT-2026-001")
    # 格式白名单
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001"), L("采购单号：PO-12345"))], {"no_format_regex": r"^HT-\d{4}-\d{3}$"})
    check("格式白名单", fno(r) == "HT-2026-001" and cp(r).get("filtered", {}).get("format") == 1)
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001"))], {"no_format_regex": "["})
    check("非法正则回退", fno(r) is not None)
    # 首页优先（平票）
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-001")), pg(2, L("合同编号：HT-2026-002"))], {"prefer_first_page": True})
    check("首页优先平票", fno(r) == "HT-2026-001")
    # 易混字符归一化
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-O01")), pg(2, L("合同编号：HT-2026-001"))], {"normalize_confusables": True})
    check("易混跨页判一致", cp(r).get("consistent") is True and len(cp(r).get("distinctNumbers", [])) == 1)
    check("输出编号归一化", fno(r) == "HT-2026-001" and fraw(r) == "HT-2026-O01")
    r = ct.extract_contract_no([pg(1, L("合同编号：HT-2026-O01")), pg(2, L("合同编号：HT-2026-001"))], {"normalize_confusables": False})
    check("不归一化判不一致", cp(r).get("consistent") is False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        # 注入缺陷：让 extract 永远返回空命中，判据应当大面积红
        orig = ct.extract_contract_no
        ct.extract_contract_no = lambda *a, **k: {"found": None, "candidates": [], "crossPage": {
            "enabled": True, "occurrences": [], "pages": [], "distinctNumbers": [],
            "occurrenceCount": 0, "consistent": None, "chosenBy": "first", "filtered": {
                "confidence": 0, "format": 0, "total": 0}}}
        run_suite()
        ct.extract_contract_no = orig
        failed = [n for n, ok in RESULTS if not ok]
        print(f"\nSELFTEST injected broken extract → {len(failed)} checks went red")
        print("SELFTEST_OK" if len(failed) >= 10 else "SELFTEST_MISS")
        sys.exit(0 if len(failed) >= 10 else 1)

    run_suite()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\nRESULT {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(len(failed))


if __name__ == "__main__":
    main()