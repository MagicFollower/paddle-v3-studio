package com.example.contract;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class ContractController {

    @Autowired
    private JdbcTemplate jdbc;

    private static final RowMapper<Map<String, Object>> CONTRACT_MAPPER = (rs, i) -> {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("contractNo", rs.getString("contract_no"));
        m.put("title", rs.getString("title"));
        m.put("partyA", rs.getString("party_a"));
        m.put("partyB", rs.getString("party_b"));
        m.put("signDate", rs.getString("sign_date"));
        m.put("totalAmount", rs.getBigDecimal("total_amount"));
        m.put("status", rs.getString("status"));
        return m;
    };

    private static final RowMapper<Map<String, Object>> ITEM_MAPPER = (rs, i) -> {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sortOrder", rs.getInt("sort_order"));
        m.put("itemName", rs.getString("item_name"));
        m.put("spec", rs.getString("spec"));
        m.put("unit", rs.getString("unit"));
        m.put("quantity", rs.getBigDecimal("quantity"));
        m.put("unitPrice", rs.getBigDecimal("unit_price"));
        m.put("amount", rs.getBigDecimal("amount"));
        return m;
    };

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", true);
        m.put("service", "contract-source");
        m.put("springBoot", "2.7.18");
        m.put("contracts", jdbc.queryForObject("SELECT COUNT(*) FROM contract", Integer.class));
        m.put("items", jdbc.queryForObject("SELECT COUNT(*) FROM contract_item", Integer.class));
        return m;
    }

    @GetMapping("/contracts")
    public Map<String, Object> list() {
        List<Map<String, Object>> items = jdbc.query(
                "SELECT * FROM contract ORDER BY contract_no", CONTRACT_MAPPER);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("items", items);
        return m;
    }

    @GetMapping("/contracts/{contractNo}")
    public ResponseEntity<?> byNo(@PathVariable String contractNo) {
        List<Map<String, Object>> found = jdbc.query(
                "SELECT * FROM contract WHERE contract_no = ?", CONTRACT_MAPPER, contractNo);
        if (found.isEmpty()) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "not_found");
            err.put("message", "合同号不存在：" + contractNo);
            return ResponseEntity.status(404).body(err);
        }
        List<Map<String, Object>> items = jdbc.query(
                "SELECT * FROM contract_item WHERE contract_no = ? ORDER BY sort_order",
                ITEM_MAPPER, contractNo);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("contract", found.get(0));
        m.put("items", items);
        return ResponseEntity.ok(m);
    }
}