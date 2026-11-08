MERGE INTO contract (contract_no, title, party_a, party_b, sign_date, total_amount, status)
KEY (contract_no) VALUES
('HT-2026-001', '办公设备采购合同', '杭州云帆科技有限公司', '上海立达办公设备有限公司', '2026-10-15', 87986.00, 'ACTIVE'),
('HT-2026-002', 'IT 耗材采购合同', '杭州云帆科技有限公司', '南京汇川商贸有限公司', '2026-10-20', 15600.00, 'ACTIVE'),
('HT-2026-003', '年度维保服务合同', '宁波海曙数科有限公司', '上海立达办公设备有限公司', '2026-11-01', 36000.00, 'ACTIVE');

MERGE INTO contract_item (contract_no, sort_order, item_name, spec, unit, quantity, unit_price, amount)
KEY (contract_no, sort_order) VALUES
('HT-2026-001', 1, '联想 ThinkPad T14 笔记本', 'i7/16G/512G', '台', 10, 6999.00, 69990.00),
('HT-2026-001', 2, '惠普 LaserJet 打印机', 'M405dn', '台', 4, 2899.00, 11596.00),
('HT-2026-001', 3, '得力 A4 复印纸', '70g 500张', '箱', 50, 128.00, 6400.00),
('HT-2026-002', 1, '硒鼓', 'CF258A', '支', 20, 480.00, 9600.00),
('HT-2026-002', 2, '网线', 'CAT6 305米', '箱', 10, 600.00, 6000.00),
('HT-2026-003', 1, '办公设备年度维保', '全年驻场', '项', 1, 36000.00, 36000.00);