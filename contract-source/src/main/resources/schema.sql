CREATE TABLE IF NOT EXISTS contract (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    contract_no VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    party_a VARCHAR(255),
    party_b VARCHAR(255),
    sign_date VARCHAR(32),
    total_amount DECIMAL(14,2),
    status VARCHAR(32) DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS contract_item (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    contract_no VARCHAR(64) NOT NULL,
    sort_order INT DEFAULT 0,
    item_name VARCHAR(255) NOT NULL,
    spec VARCHAR(255),
    unit VARCHAR(32),
    quantity DECIMAL(14,2),
    unit_price DECIMAL(14,2),
    amount DECIMAL(14,2)
);
CREATE INDEX IF NOT EXISTS idx_item_contract ON contract_item(contract_no);