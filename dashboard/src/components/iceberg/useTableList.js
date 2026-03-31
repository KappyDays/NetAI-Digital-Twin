import { useState, useEffect, useCallback } from "react";
import { executeQuery } from "../../api.js";
import { listSchemas, listTables } from "../../utils/icebergSql.js";

/**
 * useTableList — Hook to fetch available Iceberg tables for dropdown selectors.
 * Returns { tables, selectedTable, setSelectedTable, loading }
 */
export default function useTableList() {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const schemaRes = await executeQuery(listSchemas());
      const schemas = (schemaRes.columns && schemaRes.rows)
        ? schemaRes.rows.map(r => r[schemaRes.columns[0]]).filter(s => s !== "information_schema")
        : [];

      const all = [];
      for (const schema of schemas) {
        try {
          const tRes = await executeQuery(listTables(schema));
          if (tRes.columns && tRes.rows) {
            const col = tRes.columns[0];
            tRes.rows.forEach(r => all.push(`iceberg.${schema}.${r[col]}`));
          }
        } catch { /* skip schema */ }
      }
      setTables(all);
      if (all.length > 0 && !selectedTable) setSelectedTable(all[0]);
    } catch (e) {
      console.warn("Failed to list tables:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { tables, selectedTable, setSelectedTable, loading, refresh };
}
