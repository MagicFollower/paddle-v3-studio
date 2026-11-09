# -*- coding: utf-8 -*-
"""极不规范表格（合同号+明细同表）6 类形态实测：验证低成本快修可行性。

直接对 contract.table_to_entries 喂 6 类合成表格 HTML（含 ground truth），区分：
  - fixable：低成本确定性快修应解决的形态（标准/合同号在表内/多行合并表头/分类小计穿插），断言条目正确；
  - needs_llm：键值对/转置表，启发式无法泛化，记录现状（0 条）标记待 LLM 结构理解路径，不计失败。
退出码 = fixable 失败条数（0 = 快修全部达标）。

用法：.venv\\Scripts\\python.exe scripts\\check_table_irregular.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
import contract as ct

# (名称, 类别, HTML, 期望条目[关键字段])
CASES = [
    ("1-标准表(对照)", "fixable",
     '<table><tr><td>序号</td><td>品名</td><td>规格</td><td>数量</td><td>单价</td><td>金额</td></tr>'
     '<tr><td>1</td><td>甲</td><td>Q235</td><td>5</td><td>100</td><td>500</td></tr></table>',
     [{"name": "甲", "qty": 5, "price": 100, "amount": 500, "spec": "Q235"}]),
    ("2-合同号在表内(合并顶行)+明细", "fixable",
     '<table><tr><td colspan="6">合同编号：HT-2026-001</td></tr>'
     '<tr><td>序号</td><td>品名</td><td>规格</td><td>数量</td><td>单价</td><td>金额</td></tr>'
     '<tr><td>1</td><td>甲</td><td>Q235</td><td>5</td><td>100</td><td>500</td></tr></table>',
     [{"name": "甲", "qty": 5, "price": 100, "amount": 500}]),
    ("3-键值对表(标签|值交替)", "needs_llm",
     '<table><tr><td>品名</td><td>甲</td><td>规格</td><td>Q235</td></tr>'
     '<tr><td>数量</td><td>5</td><td>单价</td><td>100</td></tr>'
     '<tr><td>金额</td><td>500</td><td>单位</td><td>台</td></tr></table>',
     [{"name": "甲", "qty": 5, "price": 100, "amount": 500, "unit": "台"}]),
    ("4-转置表(字段为行,条目为列)", "needs_llm",
     '<table><tr><td>品名</td><td>甲</td><td>乙</td></tr>'
     '<tr><td>规格</td><td>Q235</td><td>Q345</td></tr>'
     '<tr><td>数量</td><td>5</td><td>6</td></tr>'
     '<tr><td>单价</td><td>100</td><td>200</td></tr>'
     '<tr><td>金额</td><td>500</td><td>1200</td></tr></table>',
     [{"name": "甲", "qty": 5, "amount": 500}, {"name": "乙", "qty": 6, "amount": 1200}]),
    ("5-多行合并表头(colspan子表头)", "fixable",
     '<table><tr><td rowspan="2">序号</td><td rowspan="2">品名</td><td colspan="2">数量信息</td><td rowspan="2">金额</td></tr>'
     '<tr><td>数量</td><td>单位</td></tr>'
     '<tr><td>1</td><td>甲</td><td>5</td><td>台</td><td>500</td></tr></table>',
     [{"name": "甲", "qty": 5, "unit": "台", "amount": 500}]),
    ("6-分类行+小计穿插", "fixable",
     '<table><tr><td>序号</td><td>品名</td><td>数量</td><td>金额</td></tr>'
     '<tr><td colspan="4">一、办公设备</td></tr>'
     '<tr><td>1</td><td>甲</td><td>5</td><td>500</td></tr>'
     '<tr><td colspan="2">小计</td><td>5</td><td>500</td></tr>'
     '<tr><td colspan="4">二、耗材</td></tr>'
     '<tr><td>2</td><td>乙</td><td>3</td><td>300</td></tr></table>',
     [{"name": "甲", "qty": 5, "amount": 500}, {"name": "乙", "qty": 3, "amount": 300}]),
]


def entry_matches(e, exp):
    for k, v in exp.items():
        got = e.get(k)
        if isinstance(v, (int, float)):
            if got is None or abs(float(got) - float(v)) > 0.01:
                return False
        elif (got or "") != v:
            return False
    return True


def evaluate(verbose=True):
    results = []
    fixable_fail = 0
    for name, kind, html, expected in CASES:
        r = ct.table_to_entries(html)
        entries = r.get("entries", [])
        names = [e.get("name") for e in entries]
        if kind == "fixable":
            ok = len(entries) == len(expected) and all(
                entry_matches(entries[i], expected[i]) for i in range(len(expected)))
            status = "PASS" if ok else "FAIL"
            if not ok:
                fixable_fail += 1
            detail = f"entries={len(entries)} names={names} headers={r.get('headers')}"
        else:
            ok = None
            status = "NEEDS_LLM"
            detail = f"现状 entries={len(entries)}（键值/转置需 LLM 结构理解；期望 {len(expected)} 条）"
        results.append((name, kind, status))
        if verbose:
            print(f"\n[{status}] {name}")
            print(f"    {detail}")
            if kind == "fixable":
                for e in entries:
                    print(f"      -> name={e.get('name')!r} spec={e.get('spec')!r} unit={e.get('unit')!r} "
                          f"qty={e.get('qty')} price={e.get('price')} amount={e.get('amount')}")
    return results, fixable_fail


def selftest():
    """自证：判据能抓到已知缺陷。注入「提取恒空」缺陷→fixable 应全红；恢复→应全绿。"""
    print("== selftest：判据活性自证 ==")
    _, base_fail = evaluate(verbose=False)
    assert base_fail == 0, f"基线应全绿，实际失败 {base_fail}"
    orig = ct.table_to_entries
    ct.table_to_entries = lambda *a, **k: {"entries": [], "headers": [], "colmap": None, "totalRow": None}
    try:
        _, broken_fail = evaluate(verbose=False)
    finally:
        ct.table_to_entries = orig
    fixable_total = sum(1 for _, k, _, _ in CASES if k == "fixable")
    assert broken_fail == fixable_total, f"注入缺陷应让 {fixable_total} 条 fixable 全红，实际 {broken_fail}"
    _, restored_fail = evaluate(verbose=False)
    assert restored_fail == 0, f"恢复后应全绿，实际 {restored_fail}"
    print(f"  基线 0 失败 / 注入恒空缺陷 {broken_fail} 红 / 恢复 0 失败")
    print("SELFTEST_OK")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    print("=" * 70)
    print("极不规范表格 6 类形态实测（低成本快修可行性）")
    print("=" * 70)
    results, fixable_fail = evaluate(verbose=True)
    fixed = sum(1 for _, k, s in results if k == "fixable" and s == "PASS")
    fixable_total = sum(1 for _, k, _ in results if k == "fixable")
    needs = sum(1 for _, k, _ in results if k == "needs_llm")
    print("\n" + "=" * 70)
    print(f"可行性结论：低成本快修解决 {fixed}/{fixable_total} 类（标准/合同号在表内/多行表头/分类小计）；"
          f"另 {needs} 类（键值对/转置）需 LLM 结构理解路径。")
    print(f"RESULT {fixed}/{fixable_total} fixable passed")
    sys.exit(fixable_fail)


if __name__ == "__main__":
    main()